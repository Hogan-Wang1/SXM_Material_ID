import numpy as np
# 兼容性补丁
if not hasattr(np, 'float'): np.float = float
if not hasattr(np, 'int'): np.int = int

import os
import matplotlib.pyplot as plt
from modules.config import logger
from modules.reader import SXMReader
from modules.analyzer import LatticeAnalyzer

def run_single_test():
    logger.info("=== 原子分辨算法专项验证 (单文件模式) ===")
    
    # 1. 获取第一个文件
    data_dir = os.path.join(os.getcwd(), "data")
    sxm_files = [f for f in os.listdir(data_dir) if f.endswith('.sxm')]
    
    if not sxm_files:
        logger.error("data 文件夹中没有找到 .sxm 文件！")
        return
    
    target_file = sxm_files[0]
    file_path = os.path.join(data_dir, target_file)
    logger.info(f"正在分析文件: {target_file}")

    # 2. 读取数据
    reader = SXMReader(file_path)
    if not reader.load_data():
        logger.error("文件读取失败")
        return

    # 3. 执行分析流水线
    # 传入原始 Z 矩阵和每个像素代表的纳米数
    analyzer = LatticeAnalyzer(reader.get_z_matrix(), reader.nm_per_pixel)
    
    processed_z = analyzer.preprocess()
    fft_mag = analyzer.compute_fft()
    peaks = analyzer.find_bragg_peaks(q_min=1.2) # 排除中心低频噪声
    results = analyzer.calculate_lattice()

    # 4. 可视化验证
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    # 子图1：原始地形图 (展示倾斜和弯曲)
    axes[0].set_title(f"Original Topography\n(Inclined/Curved)")
    im0 = axes[0].imshow(reader.get_z_matrix(), cmap='inferno')
    plt.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    
    # 子图2：平整化后的原子分辨图 (应该看到清晰的点阵)
    axes[1].set_title("After 2nd-Order Poly Fit\n(Atomic Resolution)")
    im1 = axes[1].imshow(processed_z, cmap='gray') # 原子图用灰色更清晰
    plt.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    
    # 子图3：FFT 能量谱 + 峰值标记
    axes[2].set_title("2D-FFT & Bragg Peaks\n(Red X marks the spot)")
    # 使用对数增强弱峰
    fft_log = np.log1p(fft_mag)
    axes[2].imshow(fft_log, cmap='magma')
    
    # 绘制找到的峰 (将 q 坐标转回像素坐标)
    center = np.array(fft_mag.shape) / 2
    N = fft_mag.shape[0]
    dx = reader.nm_per_pixel
    
    for qx, qy in analyzer.peaks_coord:
        # 反公式：px = q * N * dx + center
        px = qx * N * dx + center[1]
        py = qy * N * dx + center[0]
        axes[2].plot(px, py, 'rx', markersize=12, markeredgewidth=2)
        
    plt.tight_layout()
    
    # 打印最终物理结果
    if results:
        print("\n" + "="*30)
        print(f"分析结果摘要 ({target_file}):")
        print(f"晶格常数 a: {results['a']:.4f} nm")
        print(f"晶格常数 b: {results['b']:.4f} nm")
        print(f"轴间夹角  : {results['angle']:.2f}°")
        print("="*30 + "\n")
    
    plt.show()

if __name__ == "__main__":
    run_single_test()