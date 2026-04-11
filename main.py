import os
import argparse
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
import csv
from datetime import datetime
from dotenv import load_dotenv  # 新增：用于加载 .env 文件

# 加载 .env 文件中的环境变量
load_dotenv()

# ==========================================
# 导入项目模块
# ==========================================
try:
    from modules.reader import read_sxm  
    from modules.analyzer import STMAnalyzer 
    from modules.matcher import GeometricMaterialIdentifier
except ImportError as e:
    print(f"模块导入错误: {e}")
    print("请检查模块是否存在。")
    exit(1)

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="SXM_Material_ID: STM图像自动化材料识别管道 (批量处理版)")
    parser.add_argument("-c", "--chemsys", type=str, required=True, help="化学系统，例如 'Fe-Te' 或 'Bi-Se'")
    
    # 修改：将 api_key 改为可选参数，默认从环境变量读取
    parser.add_argument("-k", "--api_key", type=str, default=None, help="Materials Project API Key (覆盖 .env 中的设置)")
    
    parser.add_argument("-tl", "--tol_len", type=float, default=0.05, help="晶格常数容差比例 (默认: 0.05 即 5%)")
    parser.add_argument("-ta", "--tol_ang", type=float, default=3.0, help="晶格夹角绝对容差 (默认: 3.0度)")
    return parser.parse_args()

def select_folder():
    """调用系统窗口选择文件夹"""
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True) 
    folder_path = filedialog.askdirectory(title="请选择包含 .sxm 文件的文件夹")
    return folder_path

def main():
    # 1. 初始化命令行参数
    args = parse_arguments()

    # --- 新增：处理 API Key 逻辑 ---
    # 优先使用命令行传入的 key，如果没有，则读取 .env 文件中的 MP_API_KEY
    final_api_key = args.api_key or os.getenv("MP_API_KEY")
    
    if not final_api_key:
        print("[错误] 未找到 Materials Project API Key！")
        print("请确保已在根目录创建 .env 文件并写入 MP_API_KEY=您的密钥，或者通过 -k 参数临时传入。")
        return
    # -------------------------------

    # 2. 弹出文件夹选择界面
    print("正在等待选择文件夹...")
    target_folder = select_folder()
    
    if not target_folder:
        print("[!] 未选择文件夹，程序已退出。")
        return

    # 3. 收集所有 .sxm 文件
    sxm_files = list(Path(target_folder).rglob("*.sxm"))
    if not sxm_files:
        print(f"[!] 在 {target_folder} 中未找到任何 .sxm 文件。")
        return

    print(f"\n========== SXM Material ID 批量处理 ==========")
    print(f"目标文件夹: {target_folder}")
    print(f"发现文件数: {len(sxm_files)} 个")
    print(f"先验化学系统: {args.chemsys}")
    print(f"容差设置: 晶格 ±{args.tol_len*100}%, 角度 ±{args.tol_ang}°")
    print("API Key 来源: " + ("命令行参数" if args.api_key else ".env 配置文件"))
    print("==============================================\n")

    # 4. 设置结果输出路径
    result_dir = Path("results")
    result_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_csv = result_dir / f"Batch_Report_{args.chemsys}_{timestamp}.csv"

    # 5. 初始化几何匹配器并预拉取数据库
    print("正在初始化 Materials Project 数据库连接并拉取候选相...")
    try:
        matcher = GeometricMaterialIdentifier(
            api_key=final_api_key,  # 使用解析好的最终 key
            tolerance_length=args.tol_len, 
            tolerance_angle=args.tol_ang
        )
        matcher._query_phase_library(chemsys=args.chemsys)
    except Exception as e:
        import traceback
        print(f"[错误] 无法连接到 Materials Project 或拉取数据失败！详细错误如下：")
        traceback.print_exc()  # 这会把红色的详细报错链全部打出来
        return

    # 6. 打开 CSV 并开始批量处理流水线
    with open(report_csv, mode='w', newline='', encoding='utf-8-sig') as csv_file:
        fieldnames = ['File Name', 'Exp_a (Å)', 'Exp_b (Å)', 'Exp_gamma (°)', 'Status', 'Best Match', 'Plane', 'Theoretical Params', 'Error Score']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for idx, file_path in enumerate(sxm_files, 1):
            file_name = file_path.name
            print(f"\n[{idx}/{len(sxm_files)}] 正在分析: {file_name}")
            
            row_data = {
                'File Name': file_name,
                'Exp_a (Å)': 'N/A', 'Exp_b (Å)': 'N/A', 'Exp_gamma (°)': 'N/A',
                'Status': 'Failed', 'Best Match': 'None', 'Plane': 'None', 
                'Theoretical Params': 'None', 'Error Score': 'N/A'
            }

            try:
                # 步骤 A: 读取原始数据
                z_data, physical_info = read_sxm(str(file_path))
                
                # 步骤 B: 实例化分析器并提取特征
                analyzer = STMAnalyzer(z_data, physical_info)
                lattice_results = analyzer.find_lattice_parameters()

                if lattice_results is None:
                    raise ValueError("未能在频域中提取到足够数量的 Bragg 峰。")

                # 单位换算
                exp_a = lattice_results["a"] * 10.0
                exp_b = lattice_results["b"] * 10.0
                exp_gamma = lattice_results["angle"]
                
                # --- 新增：角度标准化处理 ---
                # 将所有大于 90 度的钝角转换为对应的锐角，保证和数据库标准一致
                if exp_gamma > 90:
                    exp_gamma = 180.0 - exp_gamma

                row_data['Exp_a (Å)'] = f"{exp_a:.3f}"
                row_data['Exp_b (Å)'] = f"{exp_b:.3f}"
                row_data['Exp_gamma (°)'] = f"{exp_gamma:.1f}"
                print(f"  -> 提取晶格: a≈{exp_a:.3f}Å, b≈{exp_b:.3f}Å, γ≈{exp_gamma:.1f}°")

                # 步骤 C: 容差几何匹配
                matched_results = matcher.match_experimental_data(
                    exp_a=exp_a, exp_b=exp_b, exp_gamma=exp_gamma, chemsys=args.chemsys
                )

                if matched_results:
                    best_match = matched_results[0]
                    row_data['Status'] = 'Success'
                    row_data['Best Match'] = best_match['Material']
                    row_data['Plane'] = f"({''.join(map(str, best_match['Plane']))})"
                    row_data['Theoretical Params'] = best_match['Theoretical']
                    row_data['Error Score'] = f"{best_match['Error Score']:.4f}"
                    print(f"  -> 最佳匹配: {row_data['Best Match']} 面: {row_data['Plane']}")
                else:
                    row_data['Status'] = 'No Match'
                    print("  -> 警告: 当前容差下未找到匹配项。")

            except Exception as e:
                print(f"  -> [错误] 处理失败: {e}")
                row_data['Status'] = f"Error: {str(e)}"

            writer.writerow(row_data)

    print(f"\n========== 批量处理完成 ==========")
    print(f"已成功分析 {len(sxm_files)} 个文件。")
    print(f"详细结果报表已保存至: {report_csv.absolute()}")

if __name__ == "__main__":
    main()