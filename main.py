import numpy as np
# 针对 NumPy 2.0+ 的全能补丁
if not hasattr(np, 'float'):
    np.float = float
if not hasattr(np, 'int'):
    np.int = int  # 解决你现在的报错

import os
from modules.config import logger
from modules.reader import SXMReader

def main():
    logger.info("--- STM 数据自动化处理启动 ---")
    
    # 获取数据文件夹路径
    data_dir = os.path.join(os.getcwd(), "data")
    
    if not os.path.exists(data_dir):
        logger.error(f"未找到目录: {data_dir}，请确认 data 文件夹存在")
        return

    # 获取所有 .sxm 文件
    files = [f for f in os.listdir(data_dir) if f.endswith('.sxm')]
    logger.info(f"在 data 目录中发现 {len(files)} 个待处理文件")

    for file_name in files:
        full_path = os.path.join(data_dir, file_name)
        reader = SXMReader(full_path)
        
        if reader.load_data():
            info = reader.get_physical_info()
            # 验证单位标准化输出
            logger.info(f"成功读取 [{file_name}]: 物理尺寸 {info['width_nm']:.2f} nm")
        else:
            # 遇到损坏文件会记录 Warning 但跳过，不会崩掉
            continue

if __name__ == "__main__":
    main()