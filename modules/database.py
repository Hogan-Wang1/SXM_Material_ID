# Materials Project API 对接、Slab 模型投影
import sqlite3
import os
import numpy as np
from mp_api.client import MPRester
from modules.config import logger, BASE_DIR, MP_API_KEY, SETTINGS

class MaterialDatabase:
    def __init__(self, db_path=None):
        """
        初始化材料数据库与缓存机制
        """
        if db_path is None:
            self.db_path = os.path.join(BASE_DIR, "data", "cache.db")
        else:
            self.db_path = db_path
            
        self.api_key = MP_API_KEY
        self._init_db()

    def _init_db(self):
        """建表：存储材料ID、化学式及 3D 晶格参数"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS materials (
                    material_id TEXT PRIMARY KEY,
                    formula TEXT,
                    a REAL, b REAL, c REAL,
                    alpha REAL, beta REAL, gamma REAL
                )
            ''')
            conn.commit()

    def fetch_materials(self, chemsys: str):
        """
        根据化学系统 (如 "Fe-Te", "U-Te") 获取数据。
        先查本地 SQLite，如果没有或需要更新，则请求 MP API。
        """
        # 1. 尝试从本地缓存读取
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 简单的模糊查询，假设数据库中存了包含该元素的化合物
            # 在实际工程中，最好建一个 chemsys 字段，这里用简化逻辑
            cursor.execute("SELECT * FROM materials WHERE formula LIKE ?", (f"%{chemsys.split('-')[0]}%",))
            cached_data = cursor.fetchall()
            
        if cached_data:
            logger.info(f"从本地缓存中加载了包含 {chemsys} 元素的材料数据。")
            return cached_data

        # 2. 如果本地没有，则调用 MP API
        logger.info(f"本地无 {chemsys} 数据，正在连接 Materials Project API...")
        if not self.api_key:
            logger.error("未找到 MP_API_KEY，请在 .env 文件中配置。")
            return []

        try:
            with MPRester(self.api_key) as mpr:
                # 获取该化学系统下的所有结构信息
                docs = mpr.materials.summary.search(chemsys=chemsys, fields=["material_id", "formula_pretty", "structure"])
                
            # 存入本地数据库
            new_data = []
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for doc in docs:
                    lattice = doc.structure.lattice
                    cursor.execute('''
                        INSERT OR IGNORE INTO materials 
                        (material_id, formula, a, b, c, alpha, beta, gamma)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (doc.material_id, doc.formula_pretty, 
                          lattice.a, lattice.b, lattice.c, 
                          lattice.alpha, lattice.beta, lattice.gamma))
                    
                    new_data.append((doc.material_id, doc.formula_pretty, 
                                     lattice.a, lattice.b, lattice.c, 
                                     lattice.alpha, lattice.beta, lattice.gamma))
                conn.commit()
            
            logger.info(f"成功从 MP 抓取并缓存了 {len(new_data)} 条记录。")
            return new_data
            
        except Exception as e:
            logger.error(f"请求 MP API 失败: {e}")
            return []

    def match_lattice(self, exp_a_nm, exp_b_nm, exp_angle, chemsys=None):
        """
        柔性匹配算法：将实验测得的 2D 参数 (nm) 与数据库中的 3D 投影进行比对。
        计算匹配得分: Score = exp(- (Delta_L^2 / 2*sigma_L^2 + Delta_A^2 / 2*sigma_A^2))
        """
        # 1. 统一单位：实验数据转为埃 (Angstrom)
        exp_a = exp_a_nm * 10.0
        exp_b = exp_b_nm * 10.0
        
        # 确保 exp_a <= exp_b 方便比对
        exp_a, exp_b = sorted([exp_a, exp_b])
        # 修正角度为锐角或钝角 (保证与数据库比对一致性，通常夹角取 <= 90)
        exp_angle = exp_angle if exp_angle <= 90 else 180 - exp_angle

        # 2. 读取容差参数
        settings = SETTINGS.get('matching', {})
        # 长度容差 sigma (默认 0.05 埃)
        sigma_l = settings.get('default_tolerance', 0.05) * 10.0 if 'default_tolerance' in settings else 0.5 
        # 角度容差 sigma (默认 2.0 度)
        sigma_a = settings.get('angle_tolerance', 2.0)
        min_score = settings.get('min_confidence', 0.5)

        # 3. 获取候选材料
        # 如果未指定 chemsys，为了安全起见，应避免全库拉取。建议在外部调用时传入，如 "Fe-Te"
        if chemsys:
            candidates = self.fetch_materials(chemsys)
        else:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM materials")
                candidates = cursor.fetchall()

        results = []
        for row in candidates:
            mat_id, formula, a, b, c, alpha, beta, gamma = row
            
            # 提取可能的 2D 解理面 (简化处理：提取三个主晶面)
            # 表面 1: ab 面 (常用于层状材料)
            # 表面 2: bc 面
            # 表面 3: ca 面
            planes = [
                {"name": "(001) ab-plane", "vecs": sorted([a, b]), "ang": gamma if gamma <= 90 else 180 - gamma},
                {"name": "(100) bc-plane", "vecs": sorted([b, c]), "ang": alpha if alpha <= 90 else 180 - alpha},
                {"name": "(010) ca-plane", "vecs": sorted([c, a]), "ang": beta if beta <= 90 else 180 - beta}
            ]

            best_score = 0
            best_plane = None

            for plane in planes:
                db_a, db_b = plane["vecs"]
                db_ang = plane["ang"]

                # 4. 计算偏差 (Delta) 与 高斯得分 (Score)
                # 使用公式: S = exp( - ( (a-a0)^2/(2*sigma_a^2) + (b-b0)^2/(2*sigma_b^2) + (ang-ang0)^2/(2*sigma_ang^2) ) )
                delta_a_sq = (exp_a - db_a)**2
                delta_b_sq = (exp_b - db_b)**2
                delta_ang_sq = (exp_angle - db_ang)**2

                exponent = - (
                    delta_a_sq / (2 * sigma_l**2) + 
                    delta_b_sq / (2 * sigma_l**2) + 
                    delta_ang_sq / (2 * sigma_a**2)
                )
                score = np.exp(exponent)

                if score > best_score:
                    best_score = score
                    best_plane = plane

            if best_score >= min_score:
                results.append({
                    "material_id": mat_id,
                    "formula": formula,
                    "matched_plane": best_plane["name"],
                    "db_params": {"a": best_plane["vecs"][0], "b": best_plane["vecs"][1], "angle": best_plane["ang"]},
                    "exp_params": {"a": exp_a, "b": exp_b, "angle": exp_angle},
                    "score": round(best_score, 4)
                })

        # 按置信度降序排列
        results = sorted(results, key=lambda x: x["score"], reverse=True)
        return results