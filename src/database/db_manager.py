import sqlite3
import os
import math
from itertools import product
from mp_api.client import MPRester
from pymatgen.core.surface import SlabGenerator
from src.utils.config import logger, BASE_DIR, MP_API_KEY

class MaterialDatabase:
    def __init__(self, db_path=None, max_miller=2):
        """
        初始化材料数据库，接管 API 请求与表面切割缓存
        """
        self.db_path = db_path or os.path.join(BASE_DIR, "data", "cache.db")
        self.api_key = MP_API_KEY
        self.max_miller = max_miller
        self._init_db()

    def _init_db(self):
        """建立本地缓存表：存储体相及其对应的所有 2D 晶面参数"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 体相基础信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS materials (
                    material_id TEXT PRIMARY KEY,
                    formula TEXT,
                    chemsys TEXT
                )
            ''')
            
            # 二维表面晶格表 (包含 a, b, gamma 及对应密勒指数)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS surfaces (
                    material_id TEXT,
                    h INTEGER, k INTEGER, l INTEGER,
                    a_th REAL, b_th REAL, gamma_th REAL,
                    FOREIGN KEY(material_id) REFERENCES materials(material_id)
                )
            ''')
            conn.commit()

    def _generate_unique_miller_indices(self):
        """生成不冗余的高指数晶面列表"""
        planes = []
        for h, k, l in product(range(self.max_miller + 1), repeat=3):
            if h == 0 and k == 0 and l == 0:
                continue
            if math.gcd(math.gcd(h, k), l) == 1:
                planes.append((h, k, l))
        return planes

    def ensure_chemsys_cached(self, chemsys: str):
        """
        检查指定化学体系是否已缓存，若无则拉取并进行高负荷的表面切割计算
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM materials WHERE chemsys = ?", (chemsys,))
            if cursor.fetchone()[0] > 0:
                logger.info(f"[{chemsys}] 体系数据与表面切片已在本地缓存，极速读取中。")
                return

        logger.info(f"本地无 [{chemsys}] 缓存。正连接 API 拉取并执行 Slab 切割，此操作视网络与材料复杂度可能需要几分钟...")
        if not self.api_key:
            raise ValueError("未找到 MP_API_KEY，无法拉取新数据。")

        target_planes = self._generate_unique_miller_indices()
        
        try:
            with MPRester(self.api_key) as mpr:
                docs = mpr.summary.search(
                    chemsys=chemsys, 
                    energy_above_hull=(0, 0.20),
                    fields=["material_id", "structure", "formula_pretty"]
                )
                
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for doc in docs:
                    mat_id = str(doc.material_id)
                    cursor.execute("INSERT OR IGNORE INTO materials (material_id, formula, chemsys) VALUES (?, ?, ?)", 
                                   (mat_id, doc.formula_pretty, chemsys))
                    
                    # 核心性能转移：在入库时就把表面切好存起来
                    for hkl in target_planes:
                        try:
                            slabgen = SlabGenerator(
                                doc.structure, hkl, min_slab_size=10, min_vacuum_size=10, center_slab=True
                            )
                            slab = slabgen.get_slab()
                            a_th, b_th, gamma_th = slab.lattice.a, slab.lattice.b, slab.lattice.gamma
                            
                            # 角度标准化
                            if gamma_th > 90.0: 
                                gamma_th = 180.0 - gamma_th
                                
                            cursor.execute('''
                                INSERT INTO surfaces (material_id, h, k, l, a_th, b_th, gamma_th)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            ''', (mat_id, hkl[0], hkl[1], hkl[2], a_th, b_th, gamma_th))
                        except Exception:
                            # 忽略无法生成该晶面的特殊体相
                            continue
                conn.commit()
            logger.info(f"成功将 [{chemsys}] 的体相及所有 2D 晶面存入数据库。后续分析将实现 O(1) 级查询。")
            
        except Exception as e:
            logger.error(f"构建数据库缓存时出错: {e}")
            raise e

    def get_all_surfaces(self, chemsys: str):
        """提供给 Matcher 的极速查询接口"""
        self.ensure_chemsys_cached(chemsys)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.formula, s.h, s.k, s.l, s.a_th, s.b_th, s.gamma_th 
                FROM surfaces s 
                JOIN materials m ON s.material_id = m.material_id 
                WHERE m.chemsys = ?
            ''', (chemsys,))
            return cursor.fetchall()