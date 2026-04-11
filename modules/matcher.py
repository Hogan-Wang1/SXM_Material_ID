import numpy as np
from mp_api.client import MPRester
from pymatgen.core.surface import SlabGenerator

class GeometricMaterialIdentifier:
    def __init__(self, api_key, tolerance_length=0.10, tolerance_angle=5.0):
        """
        初始化几何驱动的材料识别器 (MBE薄膜增强版)
        :param api_key: Materials Project API 密钥
        :param tolerance_length: 晶格常数 a, b 的容差比例（默认扩大至 10%，适应薄膜应力）
        :param tolerance_angle: 晶格夹角 gamma 的绝对容差（默认扩大至 5.0 度，适应扫描畸变）
        """
        self.api_key = api_key
        self.tol_len = tolerance_length
        self.tol_ang = tolerance_angle
        # 定义需要遍历的低指数晶面
        self.low_index_planes = [(0, 0, 1), (1, 1, 0), (1, 1, 1), (1, 0, 0), (0, 1, 0)]
        self.phase_library = {} # 用于缓存拉取的数据库结构

    def _query_phase_library(self, chemsys="Fe-Te"):
        """
        步骤 1：获取包含指定元素的物理稳定相 (过滤掉纯理论亚稳态)
        """
        candidate_structures = {}
        print(f"正在通过 mp-api 连接 Materials Project 下载 [{chemsys}] 体系结构数据...")
        
        try:
            with MPRester(self.api_key) as mpr:
                # 核心过滤：energy_above_hull=(0, 0.05) 确保只下载热力学稳定或极度接近稳定的真实相
                docs = mpr.summary.search(
                    chemsys=chemsys, 
                    energy_above_hull=(0, 0.05),
                    fields=["material_id", "structure", "formula_pretty", "energy_above_hull"]
                )
                
                for doc in docs:
                    # 强转为字符串，新版 material_id 是一个 MPID 对象
                    material_id = str(doc.material_id) 
                    structure = doc.structure
                    formula = doc.formula_pretty
                    
                    candidate_structures[material_id] = {
                        "formula": formula,
                        "structure": structure
                    }
            
            self.phase_library = candidate_structures
            print(f"成功拉取到 {len(candidate_structures)} 种真实存在的稳定体相结构。")
            return candidate_structures
            
        except Exception as e:
            print(f"[数据库连接错误] 拉取 {chemsys} 相库失败，请检查网络代理或 API Key。")
            print(f"详细报错: {e}")
            raise e

    def _extract_surface_lattices(self, structure):
        """
        步骤 2：建立候选相库，提取低指数晶面的理论二维晶格参数
        """
        surface_db = []
        for hkl in self.low_index_planes:
            try:
                # 生成表面 slab 模型（真空层大小不影响平面晶格 a,b 的提取）
                slabgen = SlabGenerator(
                    initial_structure=structure,
                    miller_index=hkl,
                    min_slab_size=10,
                    min_vacuum_size=10,
                    center_slab=True
                )
                # 获取最基本的无重构表面
                slab = slabgen.get_slab()
                
                # 提取 2D 平面晶格参数 (a, b, gamma)
                a_th = slab.lattice.a
                b_th = slab.lattice.b
                gamma_th = slab.lattice.gamma
                
                # 理论库角度标准化 (确保理论相也是锐角标准)
                if gamma_th > 90.0:
                    gamma_th = 180.0 - gamma_th
                
                surface_db.append({
                    "hkl": hkl,
                    "a_th": a_th,
                    "b_th": b_th,
                    "gamma_th": gamma_th
                })
            except Exception:
                # 某些晶格由于对称性问题可能无法生成特定 hkl 的切割面，直接跳过
                continue
                
        return surface_db

    def match_experimental_data(self, exp_a, exp_b, exp_gamma, chemsys):
        """
        步骤 3：引入容差，进行几何比对并打分
        :param exp_a, exp_b, exp_gamma: STM 实验测得的实空间晶格参数 (单位: 埃)
        """
        matched_results = []
        
        # 鲁棒性增强：实验角度标准化 (将所有钝角转换为锐角，防止因为数学定义导致匹配失败)
        if exp_gamma > 90.0:
            exp_gamma = 180.0 - exp_gamma
            
        # 检查是否已经缓存了该体系的数据库，如果没有则拉取
        if not self.phase_library:
            self._query_phase_library(chemsys=chemsys)
        
        for mat_id, data in self.phase_library.items():
            formula = data["formula"]
            surfaces = self._extract_surface_lattices(data["structure"])
            
            for surf in surfaces:
                a_th = surf["a_th"]
                b_th = surf["b_th"]
                gamma_th = surf["gamma_th"]
                
                # 考虑到 STM 图像中的 a 和 b 可能会由于人为定义（扫描角度）而互换
                match_ab = (abs(exp_a - a_th) / a_th <= self.tol_len) and (abs(exp_b - b_th) / b_th <= self.tol_len)
                match_ba = (abs(exp_a - b_th) / b_th <= self.tol_len) and (abs(exp_b - a_th) / a_th <= self.tol_len)
                
                # 角度容差匹配
                match_angle = abs(exp_gamma - gamma_th) <= self.tol_ang
                
                if (match_ab or match_ba) and match_angle:
                    # 计算误差分数 (Error Score)，越低表示匹配度越高
                    error_a = min(abs(exp_a - a_th)/a_th, abs(exp_a - b_th)/b_th)
                    error_b = min(abs(exp_b - b_th)/b_th, abs(exp_b - a_th)/a_th)
                    # 角度误差归一化处理
                    error_score = error_a + error_b + (abs(exp_gamma - gamma_th) / 90.0)
                    
                    matched_results.append({
                        "Material": formula,
                        "MP_ID": mat_id,
                        "Plane": surf["hkl"],
                        "Theoretical": f"a={a_th:.2f}, b={b_th:.2f}, γ={gamma_th:.1f}°",
                        "Error Score": error_score
                    })
        
        # 根据误差分数从小到大排序，最有可能的结果排在最前面
        matched_results = sorted(matched_results, key=lambda x: x["Error Score"])
        return matched_results