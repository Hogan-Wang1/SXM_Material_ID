# .sxm解析
import nanonispy as nap
import numpy as np
import os
from modules.config import logger

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
            # 1. 尝试读取文件
            scan = nap.read.Scan(self.file_path)
            self.header = scan.header
            self.signals = scan.signals

            # 2. 防御性检查：检查信号量是否为空（处理只有 Header 的损坏文件）
            if not self.signals or len(self.signals) == 0:
                logger.warning(f"跳过损坏文件: {self.file_path} (检测到只有 Header 或信号缺失)")
                return False

            
            # 3. 提取地形数据 (Z Channel) - 安全写法
            z_channel = self.signals.get('Z')
            if z_channel is None:
                z_channel = self.signals.get('Z (m)')
                
            if z_channel is None:
                logger.warning(f"文件 {self.file_path} 中未找到 Z 通道信号")
                return False
            
            # 避免使用 'or' 触发 NumPy 数组布尔值判定异常
            self.z_data = z_channel.get('forward')
            if self.z_data is None:
                self.z_data = z_channel.get('backward')

            # 4. 单位标准化 (将 Meters 转换为 Nanometers)
            # Nanonis header 中的 scan_range 单位通常是米 (m)
            raw_range = self.header.get('scan_range', [0, 0])
            self.width_nm = float(raw_range[0]) * 1e9
            self.height_nm = float(raw_range[1]) * 1e9

            # 计算像素比例尺 (nm/pixel)
            pixels = self.z_data.shape[0] # 假设为正方形扫描
            if pixels > 0:
                self.nm_per_pixel = self.width_nm / pixels

            logger.info(f"成功读取: {os.path.basename(self.file_path)} | "
                        f"尺寸: {self.width_nm:.2f}nm x {self.height_nm:.2f}nm | "
                        f"分辨率: {pixels}px")
            return True

        except Exception as e:
            # 捕获所有意外异常（如格式不兼容、IO错误），确保程序不中断
            logger.warning(f"读取文件时发生未知错误 [{self.file_path}]: {str(e)}")
            return False

    def get_z_matrix(self):
        """返回用于后续 FFT 或平整化处理的矩阵"""
        return self.z_data

    def get_physical_info(self):
        """返回物理信息字典"""
        return {
            "width_nm": self.width_nm,
            "height_nm": self.height_nm,
            "nm_per_pixel": self.nm_per_pixel,
            "filename": os.path.basename(self.file_path)
        }