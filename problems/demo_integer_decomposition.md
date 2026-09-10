# 整数分解与最小和：正式外部题样例

给定整数 N > 100，找到非负整数 a、b、c，满足 N = a × b + c，并使 a + b + c 取得最小值。
有多个最优三元组时，输出任意一个。

本题现有两个完整版本：基础版 N≤10^12；大数据版 N≤2^63−1。两版统一单测试 1 秒、内存 256 MB，通过 N 的规模区分算法强度。

每个测试输入一行一个 N，输出一行三个整数 a b c。例如输入 130，可输出 10 13 0，最小和值为 23。

录制时请上传生成的 `runs/demo/integer_decomposition/sqrt_problem.jsonl` 或 `fourth_problem.jsonl`，
其中包含完整题面、固定测试、标答、校验器标识和本题资源限制。仅上传本 Markdown 不会携带私有测试。
构造方式见 [测试题包说明](../docs/integer_decomposition_dataset.md)。

来源：苏剑林「科学空间」 https://spaces.ac.cn/archives/9775

本项目将原始开放问题明确为精确最小值判定，并自行设计数据范围和时限。
