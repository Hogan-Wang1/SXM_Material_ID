# .sxm解析
import numpy as np

# --- 核心兼容性补丁：解决高版本 NumPy 缺失 float/int 属性导致 nanonispy 崩溃的问题 ---
if not hasattr(np, "float"):
    np.float = float
if not hasattr(np, "int"):
    np.int = int
if not hasattr(np, "bool"):
    np.bool = bool
if not hasattr(np, "object"):
    np.object = object

import nanonispy as nap
import os
import logging

# 如果您本地的 config.py 中没有 logger，这里提供一个基础配置确保不报错
try:
    from src.utils.config import logger
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

class SXMReader:
    """
    针对 Nanonis .sxm 文件的读取类
    功能：提取地形数据（Z-channel）、元数据提取及物理单位标准化（nm）
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.header = {}
        self.signals = {}
        self.z_data = None  # 存储提取出的地形矩阵
        
        # 物理参数（标准化为 nm）
        self.width_nm = 0.0
        self.height_nm = 0.0
        self.nm_per_pixel = 0.0

    def load_data(self):
        """
        核心读取逻辑，带有防御性设计
        """
        if not os.path.exists(self.file_path):
            logger.error(f"文件不存在: {self.file_path}")
            return False

        try:
            # 1. 尝试读取文件 (此处会触发 nanonispy 内部对 np.float/int 的调用)
            scan = nap.read.Scan(self.file_path)
            self.header = scan.header
            self.signals = scan.signals

            # 2. 防御性检查：检查信号量是否为空
            if not self.signals or len(self.signals) == 0:
                logger.warning(f"跳过损坏文件: {self.file_path} (检测到只有 Header 或信号缺失)")
                return False

            # 3. 提取地形数据 (Z Channel)
            z_channel = self.signals.get('Z')
            if z_channel is None:
                z_channel = self.signals.get('Z (m)')
                
            if z_channel is None:
                logger.warning(f"文件 {self.file_path} 中未找到 Z 通道信号")
                return False
            
            # 获取扫描矩阵，优先取 forward，没有则取 backward
            self.z_data = z_channel.get('forward')
            if self.z_data is None:
                self.z_data = z_channel.get('backward')

            if self.z_data is None:
                logger.warning(f"文件 {self.file_path} 的 Z 通道内无有效数据矩阵")
                return False

            # 4. 单位标准化 (将 Meters 转换为 Nanometers)
            # Nanonis header 中的 scan_range 单位通常是米 (m)
            raw_range = self.header.get('scan_range', [0, 0])
            self.width_nm = float(raw_range[0]) * 1e9
            self.height_nm = float(raw_range[1]) * 1e9

            # 计算像素比例尺 (nm/pixel)
            # 获取矩阵形状，处理可能存在的非正方形扫描
            rows, cols = self.z_data.shape
            if cols > 0:
                self.nm_per_pixel = self.width_nm / cols

            logger.info(f"成功读取: {os.path.basename(self.file_path)} | "
                        f"尺寸: {self.width_nm:.2f}nm x {self.height_nm:.2f}nm | "
                        f"分辨率: {cols}x{rows}px")
            return True

        except Exception as e:
            # 捕获所有意外异常，确保程序不中断
            logger.warning(f"读取文件时发生未知错误 [{os.path.basename(self.file_path)}]: {str(e)}")
            return False

    def get_z_matrix(self):
        """返回用于后续分析或平整化处理的原始矩阵"""
        return self.z_data

    def get_physical_info(self):
        """返回物理信息字典"""
        return {
            "width_nm": self.width_nm,
            "height_nm": self.height_nm,
            "nm_per_pixel": self.nm_per_pixel,
            "filename": os.path.basename(self.file_path)
        }

# ==========================================
# 供 main.py 调用的快速接口函数
# ==========================================
def read_sxm(file_path):
    """
    实例化 SXMReader 并提取所需的矩阵和物理信息字典。
    该接口直接向外输出主程序进行 FFT 和晶格计算所需的标准化数据。
    """
    reader = SXMReader(file_path)
    success = reader.load_data()
    
    if not success:
        raise ValueError(f"SXMReader 解析失败或文件已损坏: {file_path}")
        
    z_data = reader.get_z_matrix()
    physical_info = reader.get_physical_info()
    
    return z_data, physical_info