# 参与贡献

首先，感谢你考虑花时间在这个项目上 🙏

## 基本规则

- **别客气**：没有大厂那种严格的 code review 流程。改了能用就行。
- **先提 issue 再写代码**：免得你花了时间做的功能我不打算加（或者我已经在做了）。
- **commit message 语言随意**：我一个人维护，看得懂就行。中文英文都行，别中英混。

## 提 PR 的流程

1. fork 仓库
2. 从 `main` 拉分支，分支名能看出来在干嘛就行（比如 `fix-safari-bug`、`add-history-feature`）
3. 改了啥在 PR 描述里简单说两句，不用写小作文
4. 提 PR

没了。

## 代码风格

没有严格的 style guide。保持和周围代码一致就行。几个不成文的约定：

- Python：4 空格缩进，小写下划线命名
- JS：用 `const`/`let`（别 `var`），分号可加可不加（项目里两种都有，别管我 😅）
- 一个 PR 只干一件事（修 bug 就修 bug，加功能就加功能）

## 本地开发

```bash
git clone <your-fork>
cd math-modeling-assistant
pip install -r requirements.txt
python app.py --debug
```

改完跑一遍手动验证：

1. Generator 页输入测试题目 → 看能不能正常生成
2. Models 页筛选功能正常
3. Problems 页题目列表加载正常

## 加新数学模型

去 `src/models/` 照着现有模型的格式加一个文件：

```python
# src/models/new_model.py
MODEL_INFO = {
    "name": "模型名称",
    "category": "分类/聚类/预测/优化...",
    "difficulty": "基础/中级/高级",
    "applicable_problems": ["适用题型1", "适用题型2"],
    "description": "一句话描述",
    "steps": ["步骤1", "步骤2", "..."],
    "pros": ["优点1", "优点2"],
    "cons": ["缺点1"],
    "references": ["相关论文链接"],
}
```

然后在 `src/models/__init__.py` 里注册一下。

## 有问题？

直接提 issue，或者在 PR 里 @ 我。不用不好意思。
