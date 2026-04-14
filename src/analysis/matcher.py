from src.database.db_manager import MaterialDatabase

class GeometricMaterialIdentifier:
    def __init__(self, tolerance_length=0.25, tolerance_ratio=0.10, tolerance_angle=5.0, max_miller=2):
        """
        初始化纯逻辑比对引擎
        参数与之前一致，依靠本地 MaterialDatabase 提供数据支撑
        """
        self.tol_len = tolerance_length
        self.tol_ratio = tolerance_ratio
        self.tol_ang = tolerance_angle
        self.db = MaterialDatabase(max_miller=max_miller)

    def match_experimental_data(self, exp_a, exp_b, exp_gamma, chemsys):
        """
        执行实验数据与理论数据库的比对打分
        """
        matched_results = []
        
        # 实验角度标准化
        if exp_gamma > 90.0: 
            exp_gamma = 180.0 - exp_gamma
            
        # 计算实验晶格比例
        exp_ratio = max(exp_a, exp_b) / min(exp_a, exp_b)

        # 极速获取预计算好的表面参数
        surfaces = self.db.get_all_surfaces(chemsys)

        for row in surfaces:
            formula, h, k, l, a_th, b_th, gamma_th = row
            
            # 计算理论晶格比例
            th_ratio = max(a_th, b_th) / min(a_th, b_th)
            
            # 1. 对称性校验
            match_angle = abs(exp_gamma - gamma_th) <= self.tol_ang
            match_ratio = abs(exp_ratio - th_ratio) / th_ratio <= self.tol_ratio
            
            # 2. 绝对长度校验
            match_abs_ab = (abs(exp_a - a_th) / a_th <= self.tol_len) and (abs(exp_b - b_th) / b_th <= self.tol_len)
            match_abs_ba = (abs(exp_a - b_th) / b_th <= self.tol_len) and (abs(exp_b - a_th) / a_th <= self.tol_len)
            match_abs = match_abs_ab or match_abs_ba
            
            # 3. 综合打分
            if match_angle and match_ratio and match_abs:
                
                error_ratio_score = (abs(exp_ratio - th_ratio) / th_ratio) * 2.0
                error_angle_score = (abs(exp_gamma - gamma_th) / 90.0) * 2.0
                
                if match_abs_ab and match_abs_ba:
                    error_len_score = min(abs(exp_a - a_th)/a_th + abs(exp_b - b_th)/b_th, 
                                          abs(exp_a - b_th)/b_th + abs(exp_b - a_th)/a_th) * 0.5
                elif match_abs_ab:
                    error_len_score = (abs(exp_a - a_th)/a_th + abs(exp_b - b_th)/b_th) * 0.5
                else:
                    error_len_score = (abs(exp_a - b_th)/b_th + abs(exp_b - a_th)/a_th) * 0.5
                    
                error_score = error_ratio_score + error_angle_score + error_len_score
                
                matched_results.append({
                    "Material": formula,
                    "Plane": (h, k, l),
                    "Theoretical": f"a={a_th:.2f}, b={b_th:.2f}, γ={gamma_th:.1f}°",
                    "Error Score": error_score
                })
                
        # 按误差得分从小到大排序返回
        return sorted(matched_results, key=lambda x: x["Error Score"])