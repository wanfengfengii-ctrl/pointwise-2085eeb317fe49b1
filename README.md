# 华澄计量试验室换表复测台账

白班依据作业单登记试验方案和带校准出处的仪表修订。冻结人员按号出件，夜班收件后使用同一条实际驱动和实际留拍复判。复测班据报告确定在本次条件下可辨的最早拍号，并能在勘误后以原报告号追查结论。

## 运行

从项目根目录使用 Python 3.11。项目只使用标准库。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 由运行平台提供。直接运行完整 unittest 套件的命令为 `python3 -B -m unittest discover -s tests -t .`。演示从 `samples/retest.json` 登记有限样例，在独立临时目录建立两座 SQLite 库。

## 一个工作日

1. 技术员固定作业单的方案号、拍号、秒时标和驱动通道及单位。
2. 校准员登记同一仪表的两个修订，记录模型与各自的校准出处。
3. 冻结人员按指定修订发行自足站件，台架保有内部模型和原校准行。
4. 夜班实收两份站件，记录它们的固定实收号并关闭台架库。
5. 夜班用实际驱动和保留拍提交复判，报告和成功回执一同入账。样例脉冲全留两拍时第 2 拍可辨，仅留任一拍时无法区分。
6. 次日校准员追加勘误。夜班选用新实收件独立签发，样例更正后两拍可共用波形。
7. 复测班重开中心库，按旧报告号核对原请求、裁决、双件出处及成功回执。

## Python 接口

调用者分别用 `sqlite3.connect` 打开台架库和中心库并负责关闭连接。每次打开台架库调用下列三个初始化函数，每次打开中心库调用后两个。初始化补建表并保留既有数据。写入入口自行提交，调用时连接应无调用方未提交的事务。同一个连接按顺序使用。

```python
from protocol.schedule import init_schedule_storage, register_schedule
from catalog.revisions import init_revision_storage, register_revision
from issuer.freeze import init_issue_storage, issue
from intake.receipts import init_receipt_storage
from intake.admission import admit
from review.report import init_report_storage
from review.publication import review
from review.archive import get_report

# bench 和 center 是分别打开并完成上述初始化的 SQLite 连接。
schedule = register_schedule(bench, 'pulse', [(1, 0), (2, 1)], [('coil', 'V')])
ref = register_revision(
    bench, 'meter', schedule.schedule_id,
    {'A': [[1]], 'B': [[1]], 'C': [[1]], 'D': [[0]]},
    {'reference': 'CAL/01', 'rows': [['0', '0']]},
)
rev = register_revision(
    bench, 'meter', schedule.schedule_id,
    {'A': [[1]], 'B': [[-1]], 'C': [[1]], 'D': [[0]]},
    {'reference': 'CAL/02', 'rows': []}, parent_id=ref.revision_id,
)
left = admit(center, issue(bench, ref.revision_id))
right = admit(center, issue(bench, rev.revision_id))
bench.close()
report = review(center, (left.receipt_id, right.receipt_id),
                {1: {'coil': 1}, 2: {'coil': 0}}, [1, 2],
                drive_units=[('coil', 'V')])
assert report.earliest_beat == 2
assert get_report(center, report.report_id) == report
```

- `register_schedule(conn, schedule_id, beats, drive_units)` 返回 `Schedule`。`beats` 是按时标递增的 2 至 6 对 `(正整数拍号, 有理秒时标)`，拍号可不连续。通道名唯一，声明次序决定矩阵列序。原样重登复用方案，同号改义整次拒绝。
- `register_revision(conn, instrument_id, schedule_id, model, calibration, *, parent_id=None)` 追加 `Revision`。父版须已登记且属于同一仪表。校准引用为非空文本，原校准行可为空，行内单元为文本。模型按先观测再推进解释，`y[k] = C x[k] + D u[k]`，`x[k+1] = A x[k] + B u[k]`。每拍一个读值。零状态模型用 `A=[]`、`B=[]`、`C=[[]]` 和一行 `D` 表达。
- `issue(conn, revision_id)` 返回 JSON 文本并记录本次发行。V1 外层含 `version`、`piece_id`、`body`、`checksum`。SHA-256 覆盖前三项的规范 JSON，使用键排序、ASCII 转义和紧凑分隔符。正文绑定方案、公开出处和整段波形生成关系。`drive_rows` 的列按拍序再按通道声明序排列，`initial_rows` 的列只生成初态对公开读值的影响空间。原校准行与内部状态矩阵存于台架库。
- `admit(conn, text)` 验证完整站件并返回 `Receipt`。同交换件号和同规范正文重投复用原实收号及出处，同号异体拒绝。规范编码允许输入文本的空白和键顺序变化。
- `review(conn, receipt_ids, drive, retained_beats, *, drive_units)` 选定有序双件。兼容性按拍号、秒时标及有序通道和单位比较，方案号保留为业务引用。实际驱动按拍号、通道名提供，单位声明须与方案对应。保留拍允许乱序和重复，按时基归并。`Report` 保存实际请求、有序出处、`earliest_beat` 和 `success_receipt`。最早可辨拍为 `None` 表示无法区分，空留拍也可正式签存。
- `get_report(conn, report_id)` 返回指定档案的原定稿和原回执，未知号返回 `None`。领取只读中心档案。

## 关站余量签报（V2 站件）

台架关库后的换表复测不公开内部状态模型，改用冻结的初态许可。白班发行站件时给定许可：初态为基点 `origin` 加至多两条同维方向 `directions`，每条方向乘一个独立取自闭区间 `[0,1]` 的系数，系数在整段各拍共用。零向量方向与线性相关方向都允许；零状态模型给空基点和空方向表。私有模型、原校准行和初态状态坐标始终留在台架。

```python
from issuer.freeze import issue_guard
from review.publication import review_guard
from review.archive import get_guard_report

left_text = issue_guard(bench, left_revision_id, [0, 0], [[1, 0], [0, 1]])
right_text = issue_guard(bench, right_revision_id, [], [])
left = admit(center, left_text)
right = admit(center, right_text)
guard = review_guard(
    center, (left.receipt_id, right.receipt_id),
    {1: {'coil': 0}, 2: {'coil': 1}}, [1, 2], Fraction(1, 2),
    drive_units=[('coil', 'V')],
)
assert guard.margin == Fraction(1, 2) and guard.claimable
assert get_guard_report(center, guard.report_id) == guard
```

- `issue_guard(conn, revision_id, origin, directions)` 返回 V2 站件 JSON 文本（`version` 为整数 `2`），沿用 V1 的外层字段、SHA-256 摘要口径、方案与公开出处字段。V2 正文仍含 `schedule`、`provenance`、`waveform`。`waveform` 保留与 V1 同口径的 `beat_ids`、`channels`、`drive_rows`（列按拍序再按通道声明序，对任意完整驱动保全精确联合读值），并以 `permission` 取代 V1 的 `initial_rows`。`permission` 只含公开读值坐标下的 `origin_readings` 和至多两条 `direction_readings`，每行按拍序排列；其含义是各拍读值等于驱动固定项加基点读值，再加各方向读值乘各自的 `[0,1]` 共用系数，不含任何状态坐标标签。
- `admit` 同时收纳 V1 与 V2 站件。重投仍按规范 JSON 判等复用首纳号；同交换件号配不同正文或版本拒收并保留首次实收。
- `review_guard(conn, receipt_ids, drive, retained_beats, minimum_margin, *, drive_units)` 选择有序双 V2 实收号，时基、完整驱动、通道声明与留拍归并沿用 V1，归并后留拍必须非空。两版从各自许可独立选取初态，版内留拍共享本版初态，未留拍仍走完整驱动但不参与判别。`minimum_margin` 必须是正有理数，等号通过；V1 旧件混入余量签报抛 `ValueError`。
- 留拍读值向量 `y` 的得分为 `sum(w[i] * y[i])`，约束 `sum(abs(w[i])) <= 1`。签报对每个权重计算右版全体合法波形最低分减左版全体合法波形最高分，再取该差的最大值，全程精确有理运算。返回的 `GuardReport` 含 `report_id`、`drive`、`retained_beats`、有序 `evidence`、`minimum_margin`、`margin`、按左右排序且向量内按留拍顺序的有理 `waveforms`、`rule`、`claimable` 和 `success_receipt`。`rule` 为 `None` 表示零余量（此时两条波形相同），否则含 `weights`、`left_max`、`right_min` 和两界中点 `threshold`。所选波形对分别可由对应实收件实现，且各拍绝对差的最大值恰等于签出余量。余量达到门槛才可领用；正余量低于门槛仍签证据但 `claimable` 为否。
- `get_guard_report(conn, report_id)` 按原号领回原定稿和原回执，未知余量报告号返回 `None`。余量定稿与成功回执原子写入，独立于 V1 的 `reports` 表；无效申请和写入失败均无新增。V1 入口、编码、来件、定稿和原回归全部保留。

有理数接受整数、`fractions.Fraction` 和 Python 3.11 `Fraction` 可解析的字符串。空值、布尔值、浮点数和零分母拒绝。完整驱动固定后，两件分别形成公开响应集合。中心逐个扩展实际留拍前缀，使用有理消元检查两件可否实现同一条可见序列。每件的自由参数在前缀内一致，两件可以独立取值，漏采读值不加约束。计算和拍序确定，发行和签存身份为独立业务编号。

输入、维度、口径或正文错误抛出 `ValueError`，未知方案、修订或实收选择抛出 `KeyError`，存储错误沿用 `sqlite3.Error`。无效请求及提交失败均不增加正式报告或成功回执。变更通过业务入口追加，重复初始化和重开保留原有登记及已签成果。
