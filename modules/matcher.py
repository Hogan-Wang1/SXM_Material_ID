import numpy as np
import math
from itertools import product
from mp_api.client import MPRester
from pymatgen.core.surface import SlabGenerator

class GeometricMaterialIdentifier:
    def __init__(self, api_key, tolerance_length=0.25, tolerance_ratio=0.10, tolerance_angle=5.0, max_miller=2):
        """
        初始化几何驱动的材料识别器 (对称性识别增强版)
        :param tolerance_length: 绝对长度容差，默认 25% (0.25)，极大包容 STM 压电陶瓷标定误差
        :param tolerance_ratio: a/b 比例容差，默认 10% (0.10)，核心用于识别晶系对称性(四方/六方等)
        :param tolerance_angle: 晶格夹角 gamma 容差，默认 5.0 度，用于锁定晶系
        :param max_miller: 密勒指数最大搜索范围 (默认寻找高指数晶面)
        """
        self.api_key = api_key
        self.tol_len = tolerance_length
        self.tol_ratio = tolerance_ratio
        self.tol_ang = tolerance_angle
        self.max_miller = max_miller
        self.phase_library = {}
        
        # 自动生成所有唯一的中高指数晶面
        self.target_planes = self._generate_unique_miller_indices()

    def _generate_unique_miller_indices(self):
        """利用最大公约数过滤，生成不冗余的晶面列表"""
        planes = []
        for h, k, l in product(range(self.max_miller + 1), repeat=3):
            if h == 0 and k == 0 and l == 0:
                continue
            if math.gcd(math.gcd(h, k), l) == 1:
                planes.append((h, k, l))
        return planes

    def _query_phase_library(self, chemsys="Fe-Te"):
        candidate_structures = {}
        print(f"正在通过 mp-api 连接 Materials Project 下载 [{chemsys}] 体系结构数据...")
        
        try:
            with MPRester(self.api_key) as mpr:
                # 能量护城河：0.20 包容 DFT 固有误差
                docs = mpr.summary.search(
                    chemsys=chemsys, 
                    energy_above_hull=(0, 0.20),
                    fields=["material_id", "structure", "formula_pretty", "energy_above_hull"]
                )
                for doc in docs:
                    material_id = str(doc.material_id) 
                    candidate_structures[material_id] = {
                        "formula": doc.formula_pretty,
                        "structure": doc.structure
                    }
            self.phase_library = candidate_structures
            print(f"成功拉取到 {len(candidate_structures)} 种稳定体相结构。将对 {len(self.target_planes)} 个不同晶面进行展开。")
            return candidate_structures
        except Exception as e:
            raise e

    def _extract_surface_lattices(self, structure):
        surface_db = []
        for hkl in self.target_planes:
            try:
                slabgen = SlabGenerator(
                    initial_structure=structure, miller_index=hkl,
                    min_slab_size=10, min_vacuum_size=10, center_slab=True
                )
                slab = slabgen.get_slab()
                a_th = slab.lattice.a
                b_th = slab.lattice.b
                gamma_th = slab.lattice.gamma
                
                # 理论库角度标准化
                if gamma_th > 90.0: 
                    gamma_th = 180.0 - gamma_th
                
                surface_db.append({
                    "hkl": hkl, "a_th": a_th, "b_th": b_th, "gamma_th": gamma_th
                })
            except Exception:
                continue
        return surface_db

    def match_experimental_data(self, exp_a, exp_b, exp_gamma, chemsys):
        matched_results = []
        
        # 实验角度标准化
        if exp_gamma > 90.0: 
            exp_gamma = 180.0 - exp_gamma
            
        if not self.phase_library:
            self._query_phase_library(chemsys=chemsys)
        
        # 计算实验晶格比例 (总是保证大数除以小数，方便对比)
        exp_ratio = max(exp_a, exp_b) / min(exp_a, exp_b)

        for mat_id, data in self.phase_library.items():
            surfaces = self._extract_surface_lattices(data["structure"])
            for surf in surfaces:
                a_th, b_th, gamma_th = surf["a_th"], surf["b_th"], surf["gamma_th"]
                
                # 计算理论晶格比例
                th_ratio = max(a_th, b_th) / min(a_th, b_th)
                
                # 1. 核心对称性校验：角度是否匹配？
                match_angle = abs(exp_gamma - gamma_th) <= self.tol_ang
                
                # 2. 核心对称性校验：a/b 比例是否匹配 (容忍 10% 的形状畸变)
                match_ratio = abs(exp_ratio - th_ratio) / th_ratio <= self.tol_ratio
                
                # 3. 兜底校验：绝对长度是否在超级宽容的范围内 (防止错把 3Å 匹配成 15Å 的超大原胞)
                # 只要有一种对应关系满足 <= 25% 即可
                match_abs_ab = (abs(exp_a - a_th) / a_th <= self.tol_len) and (abs(exp_b - b_th) / b_th <= self.tol_len)
                match_abs_ba = (abs(exp_a - b_th) / b_th <= self.tol_len) and (abs(exp_b - a_th) / a_th <= self.tol_len)
                match_abs = match_abs_ab or match_abs_ba
                
                # 必须同时满足三个条件：角度对、比例对、大小别错得太离谱
                if match_angle and match_ratio and match_abs:
                    
                    # 重新设计误差分数计算逻辑 (Error Score)
                    # 赋予比例和角度极高的权重 (重视对称性)，绝对长度误差权重降低 (包容标定系数漂移)
                    error_ratio_score = (abs(exp_ratio - th_ratio) / th_ratio) * 2.0
                    error_angle_score = (abs(exp_gamma - gamma_th) / 90.0) * 2.0
                    
                    # 长度取最佳匹配方向的相对误差
                    if match_abs_ab and match_abs_ba:
                        error_len_score = min(abs(exp_a - a_th)/a_th + abs(exp_b - b_th)/b_th, 
                                              abs(exp_a - b_th)/b_th + abs(exp_b - a_th)/a_th) * 0.5
                    elif match_abs_ab:
                        error_len_score = (abs(exp_a - a_th)/a_th + abs(exp_b - b_th)/b_th) * 0.5
                    else:
                        error_len_score = (abs(exp_a - b_th)/b_th + abs(exp_b - a_th)/a_th) * 0.5
                        
                    # 综合打分：越低越好
                    error_score = error_ratio_score + error_angle_score + error_len_score
                    
                    matched_results.append({
                        "Material": data["formula"],
                        "Plane": surf["hkl"],
                        "Theoretical": f"a={a_th:.2f}, b={b_th:.2f}, γ={gamma_th:.1f}°",
                        "Error Score": error_score
                    })
                    
        return sorted(matched_results, key=lambda x: x["Error Score"])