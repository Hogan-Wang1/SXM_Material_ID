import argparse
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import csv
from datetime import datetime

# 导入重构后的 src 模块
from src.utils.config import logger
from src.io.reader import read_sxm
from src.analysis.analyzer import STMAnalyzer
from src.analysis.matcher import GeometricMaterialIdentifier

class BatchPipeline:
    """
    SXM 自动化批量处理流水线封装类
    纯净的业务逻辑控制器，不包含任何 UI 弹窗逻辑
    """
    def __init__(self, target_folder, chemsys, tol_len=0.25, tol_ratio=0.10, tol_ang=5.0):
        self.target_folder = Path(target_folder)
        self.chemsys = chemsys
        
        logger.info(f"[{self.chemsys}] 初始化比对引擎中...")
        self.matcher = GeometricMaterialIdentifier(
            tolerance_length=tol_len, 
            tolerance_ratio=tol_ratio,
            tolerance_angle=tol_ang
        )
        
        # 预热数据库缓存：如果本地没有切好的表面数据，这里会自动拉取并计算
        self.matcher.db.ensure_chemsys_cached(self.chemsys)

    def run(self):
        """执行完整的文件夹遍历与分析流程"""
        sxm_files = list(self.target_folder.rglob("*.sxm"))
        if not sxm_files:
            logger.error(f"[!] 在 {self.target_folder} 中未找到任何 .sxm 文件。程序已退出。")
            return

        logger.info(f"\n========== SXM Material ID 批量分析 ==========")
        logger.info(f"目标文件夹: {self.target_folder} | 发现文件: {len(sxm_files)} 个")

        # 准备输出目录
        result_dir = Path("results")
        result_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_csv = result_dir / f"Batch_Report_{self.chemsys}_{timestamp}.csv"

        self._process_and_write(sxm_files, report_csv)
        logger.info(f"\n[成功] 批量处理完成！详细报表已保存至: {report_csv.absolute()}")

    def _process_and_write(self, sxm_files, report_csv):
        """核心的文件遍历、分析与 CSV 写入逻辑"""
        fieldnames = [
            'File Name', 'Exp_a (Å)', 'Exp_b (Å)', 'Exp_gamma (°)', 'Status', 
            'Rank 1 Match', 'Rank 1 Plane', 'Rank 1 Score',
            'Rank 2 Match', 'Rank 2 Plane', 'Rank 2 Score',
            'Rank 3 Match', 'Rank 3 Plane', 'Rank 3 Score'
        ]
        
        with open(report_csv, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for idx, file_path in enumerate(sxm_files, 1):
                logger.info(f"[{idx}/{len(sxm_files)}] 正在分析: {file_path.name}")
                
                # 初始化单行数据
                row = {key: 'N/A' for key in fieldnames}
                row['File Name'] = file_path.name
                row['Status'] = 'Failed'

                try:
                    # 步骤 A: 读取与实空间/频域分析
                    z_data, physical_info = read_sxm(str(file_path))
                    analyzer = STMAnalyzer(z_data, physical_info)
                    lattice_results = analyzer.find_lattice_parameters()

                    if not lattice_results:
                        raise ValueError("未在 2D-FFT 中提取到有效 Bragg 峰")

                    # 步骤 B: 单位换算与角度清洗
                    exp_a = lattice_results["a"] * 10.0
                    exp_b = lattice_results["b"] * 10.0
                    exp_gamma = lattice_results["angle"]
                    if exp_gamma > 90.0: 
                        exp_gamma = 180.0 - exp_gamma
                        
                    row.update({
                        'Exp_a (Å)': f"{exp_a:.3f}", 
                        'Exp_b (Å)': f"{exp_b:.3f}", 
                        'Exp_gamma (°)': f"{exp_gamma:.1f}"
                    })

                    # 步骤 C: 毫秒级数据库比对
                    matches = self.matcher.match_experimental_data(
                        exp_a=exp_a, exp_b=exp_b, exp_gamma=exp_gamma, chemsys=self.chemsys
                    )

                    # 步骤 D: 结果格式化写入
                    if matches:
                        row['Status'] = 'Success'
                        for i in range(min(3, len(matches))):
                            row[f'Rank {i+1} Match'] = matches[i]['Material']
                            row[f'Rank {i+1} Plane'] = f"({''.join(map(str, matches[i]['Plane']))})"
                            row[f'Rank {i+1} Score'] = f"{matches[i]['Error Score']:.4f}"
                    else:
                        row['Status'] = 'No Match'
                        
                except Exception as e:
                    row['Status'] = f"Error: {str(e)}"
                    logger.warning(f"处理文件 {file_path.name} 时遇到错误: {e}")
                    
                writer.writerow(row)


def select_folder_ui():
    """调用系统窗口选择文件夹 (纯 UI 交互逻辑)"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True) 
    return filedialog.askdirectory(title="请选择包含 .sxm 文件的文件夹")


if __name__ == "__main__":
    # 解析命令行参数，提供更强的终端控制能力
    parser = argparse.ArgumentParser(description="SXM Material ID 自动化分析流水线")
    parser.add_argument("--chemsys", type=str, default="Fe-Te", help="目标化学体系 (默认: Fe-Te)")
    parser.add_argument("--tol_len", type=float, default=0.25, help="绝对长度容差 (默认: 0.25，即包容 25% 误差)")
    parser.add_argument("--tol_ratio", type=float, default=0.10, help="a/b 比例容差 (默认: 0.10，即包容 10% 畸变)")
    parser.add_argument("--tol_ang", type=float, default=5.0, help="晶格角度容差 (默认: 5.0 度)")
    
    args = parser.parse_args()

    print("\n===========================================")
    print("      SXM Material ID Pipeline v2.0")
    print("===========================================")
    print("请在弹出的窗口中选择包含 .sxm 数据的文件夹...\n")

    # 1. 触发 UI 获取路径
    folder_path = select_folder_ui()
    
    if not folder_path:
        print("[!] 未选择文件夹，程序已安全退出。")
        exit(0)

    # 2. 实例化流水线并启动
    pipeline = BatchPipeline(
        target_folder=folder_path, 
        chemsys=args.chemsys,
        tol_len=args.tol_len,
        tol_ratio=args.tol_ratio,
        tol_ang=args.tol_ang
    )
    
    pipeline.run()