import numpy as np
import matplotlib.pyplot as plt
import os
from scipy import ndimage, optimize
from modules.config import logger

class STMAnalyzer:
    def __init__(self, z_data, physical_info):
        """
        初始化分析器
        :param z_data: 原始扫描矩阵 (由 SXMReader 提供)
        :param physical_info: 包含宽度、分辨率等信息的字典
        """
        self.z_raw = np.copy(z_data)
        self.z_processed = None
        self.fft_magnitude = None
        self.info = physical_info
        self.filename = physical_info.get("filename", "unknown")
        
        # 基础物理参数
        self.nx, self.ny = z_data.shape
        self.width_nm = physical_info['width_nm']
        self.height_nm = physical_info['height_nm']
        self.pad_factor = 4 # 默认插值倍数，提高FFT精度

    def preprocess(self, sigma=1):
        """
        图像预处理：平面校准 + 逐行中值拉平 + 滤波
        """
        # A. 最小二乘法平面拟合
        X, Y = np.meshgrid(np.arange(self.ny), np.arange(self.nx))
        A = np.c_[X.flatten(), Y.flatten(), np.ones(X.size)]
        coeffs, _, _, _ = np.linalg.lstsq(A, self.z_raw.flatten(), rcond=None)
        plane = (coeffs[0]*X + coeffs[1]*Y + coeffs[2])
        
        # B. 减去平面并消除行间扫描漂移 (Line-by-line leveling)
        self.z_processed = self.z_raw - plane
        self.z_processed -= np.median(self.z_processed, axis=1, keepdims=True)

        # C. 适度中值滤波去除尖锐噪点
        self.z_processed = ndimage.median_filter(self.z_processed, size=3)
        logger.info(f"[{self.filename}] 预处理完成。")

    def compute_2d_fft(self, pad_factor=4):
        """
        执行 2D-FFT 并引入 Zero-Padding 以提高频域分辨率
        """
        if self.z_processed is None:
            self.preprocess()
            
        self.pad_factor = pad_factor
        # 施加汉宁窗减少边缘效应
        win = np.hanning(self.nx)[:, None] * np.hanning(self.ny)[None, :]
        
        # 零填充插值：将图像扩充到原尺寸的 pad_factor 倍
        pad_x = self.nx * self.pad_factor
        pad_y = self.ny * self.pad_factor
        
        fft_data = np.fft.fft2(self.z_processed * win, s=(pad_x, pad_y))
        self.fft_magnitude = np.fft.fftshift(np.abs(fft_data))
        
        self.fft_nx, self.fft_ny = pad_x, pad_y
        logger.info(f"[{self.filename}] FFT计算完成 (插值分辨率: {pad_x}x{pad_y})。")

    @staticmethod
    def _gaussian_2d(coords, amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
        """亚像素定位用的2D高斯函数"""
        x, y = coords
        a = (np.cos(theta)**2)/(2*sigma_x**2) + (np.sin(theta)**2)/(2*sigma_y**2)
        b = -(np.sin(2*theta))/(4*sigma_x**2) + (np.sin(2*theta))/(4*sigma_y**2)
        c = (np.sin(theta)**2)/(2*sigma_x**2) + (np.cos(theta)**2)/(2*sigma_y**2)
        g = amplitude * np.exp( - (a*((x-xo)**2) + 2*b*(x-xo)*(y-yo) + c*((y-yo)**2))) + offset
        return g.ravel()

    def find_lattice_parameters(self):
        """
        核心算法：自动寻找 Bragg 峰并执行 2D 高斯拟合
        """
        if self.fft_magnitude is None:
            self.compute_2d_fft()

        # 1. 动态计算搜索步长（基于物理单位）
        df_x = 1.0 / (self.width_nm * self.pad_factor)
        df_y = 1.0 / (self.height_nm * self.pad_factor)
        
        # 设置寻找局部最大值的窗口大小 (约 2 nm^-1 范围)
        pixel_dist = int(2.0 / (2 * np.pi * df_x)) 
        pixel_dist = max(8, pixel_dist)

        data_max = ndimage.maximum_filter(self.fft_magnitude, size=pixel_dist)
        maxima = (self.fft_magnitude == data_max)
        
        # 2. 屏蔽中心区域 (屏蔽 q < 5 nm^-1 的低频分量)
        cx, cy = self.fft_nx // 2, self.fft_ny // 2
        mask_q = 5.0 
        margin_x = int(mask_q / (2 * np.pi * df_x))
        margin_y = int(mask_q / (2 * np.pi * df_y))
        maxima[cy-margin_y:cy+margin_y, cx-margin_x:cx+margin_x] = False
        
        labeled, _ = ndimage.label(maxima)
        slices = ndimage.find_objects(labeled)
        
        candidates = []
        for sl in slices:
            y, x = sl[0].start, sl[1].start
            candidates.append((x, y, self.fft_magnitude[y, x]))
        
        # 取最强的 4 个峰
        peaks = sorted(candidates, key=lambda x: x[2], reverse=True)[:4]
        
        fit_results = []
        for px, py, p_val in peaks:
            w = 12 # 拟合窗口
            y_min, y_max = max(0, py-w), min(self.fft_ny, py+w)
            x_min, x_max = max(0, px-w), min(self.fft_nx, px+w)
            
            x_mesh, y_mesh = np.meshgrid(np.arange(x_min, x_max), np.arange(y_min, y_max))
            try:
                region = self.fft_magnitude[y_min:y_max, x_min:x_max]
                p0 = [p_val, px, py, 4, 4, 0, np.min(region)]
                popt, _ = optimize.curve_fit(self._gaussian_2d, (x_mesh, y_mesh), region.ravel(), p0=p0)
                fit_results.append((popt[1], popt[2])) 
            except:
                fit_results.append((px, py))

        # 3. 倒格矢与实空间换算
        q_vecs = []
        for fx, fy in fit_results:
            qx = (fx - cx) * (2 * np.pi * df_x)
            qy = (fy - cy) * (2 * np.pi * df_y)
            q_vecs.append(np.array([qx, qy]))

        if len(q_vecs) >= 2:
            v1 = q_vecs[0]
            v2 = next((v for v in q_vecs[1:] if np.abs(np.dot(v1, v)/(np.linalg.norm(v1)*np.linalg.norm(v))) < 0.8), None)
            
            if v2 is not None:
                area_q = np.abs(np.cross(v1, v2))
                a_vec = 2 * np.pi * np.array([v2[1], -v2[0]]) / area_q
                b_vec = 2 * np.pi * np.array([-v1[1], v1[0]]) / area_q
                a, b = np.linalg.norm(a_vec), np.linalg.norm(b_vec)
                angle = np.degrees(np.arccos(np.dot(a_vec, b_vec)/(a*b)))
                
                return {"a": a, "b": b, "angle": angle, "q_peaks": fit_results, "q_vecs": q_vecs}
        return None

    def visualize_all(self, results=None, save_path="results", zoom_range=25):
        """
        输出最终验证图像
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # 左图：实空间原子形貌
        im1 = ax1.imshow(self.z_processed, cmap='afmhot', origin='lower',
                         extent=[0, self.width_nm, 0, self.height_nm])
        ax1.set_title(f"Real Space (nm): {self.filename}")
        ax1.set_xlabel("x (nm)")
        ax1.set_ylabel("y (nm)")
        plt.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)

        # 右图：高分辨率倒空间 (物理单位坐标)
        kx_max = np.pi / (self.width_nm / self.nx)
        ky_max = np.pi / (self.height_nm / self.ny)
        
        fft_log = np.log10(self.fft_magnitude + 1)
        im2 = ax2.imshow(fft_log, cmap='magma', origin='lower',
                         extent=[-kx_max, kx_max, -ky_max, ky_max])
        
        # 标注拟合点
        if results:
            for qx, qy in results.get("q_vecs", []):
                ax2.scatter(qx, qy, s=100, edgecolors='cyan', facecolors='none', lw=2)
            
            info_text = f"a: {results['a']:.4f} nm\nb: {results['b']:.4f} nm\nAngle: {results['angle']:.1f}°"
            ax1.text(0.05, 0.95, info_text, transform=ax1.transAxes, color='white',
                     fontsize=12, fontweight='bold', bbox=dict(facecolor='black', alpha=0.7))

        ax2.set_xlim([-zoom_range, zoom_range])
        ax2.set_ylim([-zoom_range, zoom_range])
        ax2.set_title(f"2D-FFT High-Res Zoom ($\pm${zoom_range} $nm^{{-1}}$)")
        ax2.set_xlabel("$q_x (nm^{-1})$")
        ax2.set_ylabel("$q_y (nm^{-1})$")
        
        plt.tight_layout()
        if not os.path.exists(save_path): os.makedirs(save_path)
        plt.savefig(os.path.join(save_path, f"final_verify_{self.filename}.png"), dpi=300)
        plt.show()