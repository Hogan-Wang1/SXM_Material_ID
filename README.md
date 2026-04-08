# SXM_Material_ID

## 1. 项目简介
本项目旨在开发一套自动化的 STM 原子分辨图像分析流水线，实现从原始 `.sxm` 数据到材料物相识别的转化，特别针对 MBE 生长的量子材料系统（如超导体、拓扑绝缘体）。

## 2. 核心技术路径 (The Workflow)
### 1) 图像预处理 (Preprocessing)
- **Flattening**: 去除样品倾斜背景。
- **Drift Correction**: 基于标准参考物或对称性约束校正压电陶瓷漂移。
- **Filtering**: 使用高斯/维纳滤波抑制电子学噪声。

### 2) 晶体周期性提取 (Feature Extraction)
- **2D-FFT**: 转换至频域。
- **Auto-Peak Finding**: 自动识别 Bragg 峰位置。
- **Lattice Calculation**: 推导实空间晶格矢量 $\vec{a}, \vec{b}$ 及夹角 $\gamma$。

### 3) 智能比对 (Material Identification)
- **Database Query**: 通过 API 连接 Materials Project 数据库。
- **Slab Projection**: 将三维体相数据沿特定晶面 (hkl) 投影为二维表面。
- **Scoring System**: 根据晶格参数匹配度评分，输出 top-k 候选材料。

## 3. 依赖项 (Requirements)
- `nanonispy`: .sxm 文件解析
- `pySPM`: 扫描探针显微数据处理
- `pymatgen`: 材料科学数据库对接
- `scikit-image`: 图像处理算法

## 4. 关键挑战 (Pending)
- 如何处理 MBE 生长中常见的**表面重构（Surface Reconstruction）**导致周期性与体相不一致的问题。
- 提高在低信噪比图像下的 Bragg 峰识别精度。