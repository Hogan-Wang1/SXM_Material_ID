import numpy as np
from scipy import ndimage, optimize
from modules.config import logger

class LatticeAnalyzer:
    def __init__(self, z_data, nm_per_pixel):
        self.raw_data = z_data
        self.nm_per_pixel = nm_per_pixel
        self.processed_data = None
        self.fft_magnitude = None
        
        self.peaks_coord = [] 
        self.lattice_params = {}

    # --- 1. 高精度预处理：二次曲面背景扣除 ---
    def preprocess(self):
        """
        对于原子分辨图像，最主要的是消除压电陶瓷蠕变(Creep)和热漂移导致的曲面弯曲。
        使用 2D 二次多项式拟合 (2nd-order polynomial surface fit) 是 STM 领域的标配。
        """
        data = self.raw_data.copy()
        rows, cols = data.shape
        x, y = np.meshgrid(np.arange(cols), np.arange(rows))
        
        # 将坐标展平
        x_f, y_f, z_f = x.ravel(), y.ravel(), data.ravel()
        
        # 构建二次曲面的设计矩阵: z = ax^2 + by^2 + cxy + dx + ey + f
        A = np.column_stack([x_f**2, y_f**2, x_f*y_f, x_f, y_f, np.ones_like(x_f)])
        coeffs, _, _, _ = np.linalg.lstsq(A, z_f, rcond=None)
        
        # 计算拟合出的背景曲面
        bg = (coeffs[0]*x**2 + coeffs[1]*y**2 + coeffs[2]*x*y + 
              coeffs[3]*x + coeffs[4]*y + coeffs[5])
        
        # 扣除背景
        self.processed_data = data - bg
        logger.info("原子分辨预处理完成: 已应用 2D 二次曲面背景扣除")
        return self.processed_data

    # --- 2. 傅里叶变换 ---
    def compute_fft(self):
        if self.processed_data is None:
            self.preprocess()
            
        # 汉宁窗(Hanning Window)极度重要，防止原子图边缘的突变在FFT中产生十字亮线
        window = np.hanning(self.processed_data.shape[0])[:, None] * np.hanning(self.processed_data.shape[1])
        data_windowed = self.processed_data * window
        
        fft_complex = np.fft.fftshift(np.fft.fft2(data_windowed))
        self.fft_magnitude = np.abs(fft_complex)
        return self.fft_magnitude

    # --- 3. 全角度自适应 Bragg 峰提取 ---
    def find_bragg_peaks(self, q_min=1.2, search_radius=15):
        """
        不再限制死 q_max，自动适应任意扫描角度。
        q_min 用于遮蔽中心的 1/f 低频噪声和直流信号。
        """
        if self.fft_magnitude is None:
            self.compute_fft()

        rows, cols = self.fft_magnitude.shape
        center_y, center_x = rows // 2, cols // 2
        y, x = np.mgrid[0:rows, 0:cols]

        # 计算倒空间物理坐标 q (1/nm)
        q_matrix = np.sqrt((x - center_x)**2 + (y - center_y)**2) / (rows * self.nm_per_pixel)

        # 动态遮罩：屏蔽中心低频区 (q < q_min)
        mask = q_matrix > q_min
        masked_fft = self.fft_magnitude * mask

        # 使用最大值滤波寻找局部最亮点
        data_max = ndimage.maximum_filter(masked_fft, size=search_radius)
        is_peak = (masked_fft == data_max) & mask & (masked_fft > 0)
        
        peak_coords = np.argwhere(is_peak)
        if len(peak_coords) == 0:
            logger.warning("未找到任何有效峰值，请检查图像信号强度。")
            return []

        # 提取最亮的 top 6 个峰（对于四方/正交晶格，通常会出现 4 个明显的对称一阶峰）
        intensities = [masked_fft[c[0], c[1]] for c in peak_coords]
        top_indices = np.argsort(intensities)[::-1][:6]
        top_coords = peak_coords[top_indices]

        # 亚像素高斯拟合
        self.peaks_coord = []
        for coord in top_coords:
            sub_coord = self._fit_gaussian_2d(coord)
            if sub_coord:
                qx = (sub_coord[1] - center_x) / (cols * self.nm_per_pixel)
                qy = (sub_coord[0] - center_y) / (rows * self.nm_per_pixel)
                self.peaks_coord.append((qx, qy))
        
        logger.info(f"成功锁定 {len(self.peaks_coord)} 个亚像素 Bragg 峰")
        return self.peaks_coord

    def _fit_gaussian_2d(self, coord, window_size=5):
        """高精度 2D 高斯拟合，提取亚像素级坐标"""
        y0, x0 = coord
        w = window_size
        
        # 避免边界溢出
        if y0-w < 0 or y0+w+1 > self.fft_magnitude.shape[0] or x0-w < 0 or x0+w+1 > self.fft_magnitude.shape[1]:
            return (y0, x0)
            
        z_sub = self.fft_magnitude[y0-w:y0+w+1, x0-w:x0+w+1]
        y_sub, x_sub = np.mgrid[-w:w+1, -w:w+1]
        
        def gaussian(xy, amplitude, xo, yo, sigma, offset):
            x, y = xy
            return (amplitude * np.exp(-((x-xo)**2 + (y-yo)**2)/(2*sigma**2)) + offset).ravel()

        initial_guess = (z_sub.max() - z_sub.min(), 0, 0, 1.5, z_sub.min())
        try:
            bounds = ([0, -w, -w, 0.5, 0], [np.inf, w, w, w*2, np.inf])
            popt, _ = optimize.curve_fit(gaussian, (x_sub, y_sub), z_sub.ravel(), p0=initial_guess, bounds=bounds)
            return (y0 + popt[2], x0 + popt[1])
        except:
            return (y0, x0)

    # --- 4. 晶体学参数计算 ---
    def calculate_lattice(self):
        if len(self.peaks_coord) < 2:
            return None

        # 将峰按距中心距离(q的大小)排序，优先使用一阶峰
        qs = sorted(self.peaks_coord, key=lambda x: np.linalg.norm(x))
        q1 = np.array(qs[0])
        q2 = None
        
        # 寻找第二基矢：必须与 q1 不共线（夹角不能接近 0 或 180 度）
        for i in range(1, len(qs)):
            cos_val = np.dot(q1, qs[i]) / (np.linalg.norm(q1) * np.linalg.norm(qs[i]))
            angle_deg = np.degrees(np.arccos(np.clip(cos_val, -1.0, 1.0)))
            
            # 通常两个基矢的夹角在 60 到 120 度之间
            if 45 < angle_deg < 135: 
                q2 = np.array(qs[i])
                break
        
        if q2 is None: 
            logger.error("未能找到两个非共线的正交/斜交基矢")
            return None

        # 计算实空间参数: a, b = 1/|q|
        a = 1.0 / np.linalg.norm(q1)
        b = 1.0 / np.linalg.norm(q2)
        
        cos_theta = np.dot(q1, q2) / (np.linalg.norm(q1) * np.linalg.norm(q2))
        angle = np.degrees(np.arccos(np.clip(cos_theta, -1.0, 1.0)))

        self.lattice_params = {"a": a, "b": b, "angle": angle}
        logger.info(f"== 物理参数解析成功 ==")
        logger.info(f"   a = {a:.3f} nm, b = {b:.3f} nm, 晶面夹角 = {angle:.1f}°")
        return self.lattice_params