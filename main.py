import os
import csv
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
import matplotlib
# 强制使用后台后端，禁止分析图弹出
matplotlib.use('Agg') 

from modules.reader import SXMReader
from modules.analyzer import STMAnalyzer
from modules.database import MaterialDatabase
from modules.config import logger, BASE_DIR

def select_folder_gui():
    """弹出 GUI 界面选择文件夹"""
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes('-topmost', True)  # 确保对话框在最前面
    
    logger.info("正在等待用户选择目标文件夹...")
    target_dir = filedialog.askdirectory(title="请选择包含 .sxm 文件的文件夹")
    
    root.destroy() # 关闭 tkinter 实例
    return target_dir

def init_run_folder(target_dir):
    """根据目标文件夹名称和当前时间创建唯一的存储目录"""
    folder_name = os.path.basename(os.path.normpath(target_dir))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    results_root = os.path.join(BASE_DIR, "results")
    current_run_dir = os.path.join(results_root, f"{timestamp}_{folder_name}")
    
    os.makedirs(current_run_dir, exist_ok=True)
    return results_root, current_run_dir

def main():
    # 1. 弹出文件夹选择界面
    target_path = select_folder_gui()
    
    if not target_path:
        logger.warning("未选择任何文件夹，程序退出。")
        return

    # 2. 初始化路径逻辑
    results_root, current_run_dir = init_run_folder(target_path)
    db = MaterialDatabase()
    
    # 3. 获取目标文件夹内所有 .sxm 文件
    files = [f for f in os.listdir(target_path) if f.endswith(".sxm")]
    if not files:
        logger.warning(f"在路径 {target_path} 中未找到任何 .sxm 文件。")
        return

    logger.info(f"已选定目标：{target_path}")
    logger.info(f"分析结果将保存至：{current_run_dir}")

    summary_path = os.path.join(results_root, "summary.csv")
    csv_header = ["Timestamp", "Source_Folder", "Filename", "Status", "a(nm)", "b(nm)", "Angle", "Best_Match", "Score", "Error_Msg"]
    
    file_exists = os.path.isfile(summary_path)
    
    with open(summary_path, mode='a', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_header)
        if not file_exists:
            writer.writeheader()

        for filename in files:
            file_path = os.path.join(target_path, filename)
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row_data = {
                "Timestamp": now_time,
                "Source_Folder": os.path.basename(target_path),
                "Filename": filename,
                "Status": "Processing",
                "a(nm)": "-", "b(nm)": "-", "Angle": "-", 
                "Best_Match": "-", "Score": "-", "Error_Msg": ""
            }

            try:
                # 读取数据
                reader = SXMReader(file_path)
                if not reader.load_data():
                    raise ValueError("文件读取失败")

                # 分析晶格
                analyzer = STMAnalyzer(reader.get_z_matrix(), reader.get_physical_info())
                analyzer.preprocess()
                lattice_results = analyzer.find_lattice_parameters()

                if lattice_results:
                    a, b, ang = lattice_results['a'], lattice_results['b'], lattice_results['angle']
                    row_data.update({"a(nm)": round(a, 4), "b(nm)": round(b, 4), "Angle": round(ang, 2)})

                    # 数据库比对
                    # 注意：由于去掉了命令行，如果需要 chemsys 可以在此处手动指定或保持 None
                    matches = db.match_lattice(a, b, ang, chemsys=None)
                    if matches:
                        row_data.update({
                            "Best_Match": f"{matches[0]['formula']} ({matches[0]['material_id']})",
                            "Score": matches[0]['score'],
                            "Status": "Success"
                        })
                    else:
                        row_data["Status"] = "No_Match"

                # 静默保存分析图
                analyzer.visualize_all(results=lattice_results, save_path=current_run_dir)

            except Exception as e:
                logger.error(f"文件 {filename} 处理崩溃: {str(e)}")
                row_data["Status"] = "Failed"
                row_data["Error_Msg"] = str(e)
            finally:
                writer.writerow(row_data)
                csvfile.flush()

    logger.info(f"所有任务已完成。总结报告：{summary_path}")

if __name__ == "__main__":
    main()