# mcnp2gdml 用户手册

## 1. 工具简介

`mcnp2gdml` 用于将 MCNP 输入文件转换为 Geant4 可加载的 GDML 几何文件。

当前版本的目标是：

- 支持常见 MCNP 几何表达式（空格交集、冒号并集、括号、补集 `#`）
- 将复杂几何映射为 GDML 基本体与布尔运算
- 支持模板匹配优化（盒体、圆柱/圆柱壳、球体/球壳）
- 支持几何一致性采样验证（MCNP 判定 vs GDML 判定）

## 2. 目录结构

项目关键目录如下：

- `src/`：核心代码
- `test/`：MCNP 测试输入样例
- `doc/`：文档
- `out/`：建议用于输出 GDML、验证报告、调试文件

## 3. 运行环境

建议环境：

- Python 3.10+
- Windows / Linux

依赖：

- 标准库
- 可选：`reportlab`（仅用于生成 PDF 文档）

## 4. 基本用法

在项目根目录执行：

```bash
python src/mcnp2gdml.py <inp_file> <out_file>
```

示例：

```bash
python src/mcnp2gdml.py test/CASE_10 out/CASE_10.gdml
```

## 5. 命令行参数

### 5.1 必选参数

- `inp_file`：MCNP 输入文件路径
- `out_file`：输出 GDML 路径

### 5.2 可选参数

- `--top-cells`
  - 逗号分隔的顶层 cell ID（仅这些 cell 放置到 world）
  - 示例：`--top-cells 1,2,3`

- `--bbox`
  - 手工指定包围盒：`x0,x1,y0,y1,z0,z1`
  - 示例：`--bbox -100,100,-100,100,-50,150`

- `--bbox-margin`
  - 自动包围盒外扩比例，默认 `0.1`

- `--dump-geom [path]`
  - 导出几何 AST JSON；可省略路径，默认输出到当前目录

- `--log`
  - 打开调试日志（表达式规范化、模板命中等）

- `--validate N`
  - 启用采样验证，每个 cell 采样 `N` 个随机点

- `--validate-cells`
  - 指定参与验证的 cell 列表（逗号分隔）
  - 默认行为：若未指定则验证 `top-cells`；若也未指定则按程序默认策略

- `--validate-seed`
  - 采样随机种子，默认 `0`

- `--validate-eps`
  - 几何判定容差，默认 `1e-6`

- `--validate-out`
  - 将验证报告写入 JSON 文件

## 6. 典型命令

### 6.1 普通转换

```bash
python src/mcnp2gdml.py test/CASE_6.T9 out/CASE_6.gdml
```

### 6.2 转换并导出 AST

```bash
python src/mcnp2gdml.py test/CASE_10 out/CASE_10.gdml --dump-geom out/CASE_10.geom.json
```

### 6.3 转换并开启日志

```bash
python src/mcnp2gdml.py test/CASE-1-D out/CASE-1-D.gdml --log
```

### 6.4 转换并验证（指定 cell）

```bash
python src/mcnp2gdml.py test/CASE_10 out/CASE_10.gdml --validate 10000 --validate-cells 1,2,3 --validate-seed 42 --validate-out out/CASE_10.validate.json
```

## 7. 输出文件说明

### 7.1 GDML 文件

- 包含 `define/materials/solids/structure/setup`
- `setup/world` 引用 `World` 体
- `top-cells` 对应的 volume 作为 `physvol` 放置在 world 中

### 7.2 AST 调试文件（`--dump-geom`）

- JSON 结构表达 MCNP 几何逻辑树
- 叶子为 surface 引用，内部节点为并/交/补

### 7.3 验证报告（`--validate-out`）

报告字段示例：

- `samples`：每个 cell 的采样点数
- `cells[].cell_id`：cell 编号
- `cells[].mismatches`：不一致点个数
- `cells[].ratio`：不一致比例
- `cells[].examples`：最多 5 个反例点

## 8. 几何与算法说明（简要）

### 8.1 表达式支持

当前支持：

- 空格：交集
- `:`：并集
- `()`：分组
- `#`：补集

### 8.2 模板匹配优化

会优先识别并复用基础体：

- 盒体（box）
- 圆柱/圆柱壳（tube）
- 球体/球壳（sphere）

如果无法模板化，则回退到半空间裁剪 + 布尔构造，保证通用性。

### 8.3 几何验证

验证模式在同一采样点上比较：

1. MCNP 表达式判定结果
2. 转换后 GDML 几何判定结果

用于给出“类型、尺寸、位置一致性”的量化证据。

## 9. 常见问题

### 9.1 看到 world 里只有部分几何

请检查是否使用了 `--top-cells`。该参数控制哪些 cell 被放置到 world。

### 9.2 验证出现 mismatch

建议顺序：

1. 增大 `--validate` 采样点数
2. 固定 `--validate-seed` 便于复现
3. 调整 `--validate-eps`
4. 打开 `--log` 检查表达式规范化与模板命中

### 9.3 如何验证全量 cell

将全部 cell ID 传给 `--validate-cells`，并设置较大采样数（例如 10000 或更高）。

## 10. 版本与维护建议

建议每次修改转换逻辑后至少执行：

- 一轮 `test/` 全量转换
- 一轮关键案例的 `--validate`
- 对 mismatch 非零案例进行反例点复查

---

如需英文版手册，可在此版本基础上直接翻译并保留命令示例。
