# 河湾记忆馆口述史配音工作台

河湾市记忆馆用这个本地 JSON HTTP 服务制作《渡口口述史》的展厅音轨。采编登记采访原声，编辑确定取段和顺序，配音师照固定校样交件，导播核听实际选音，定稿员将成品签存给展厅播放器。

## 运行

使用 Python 3.11 标准库。以下命令在项目根目录执行。

```sh
python3 -B -m release.server --database workbench.sqlite3 --port 8000
python3 -B check_project.py
python3 -B demo.py
```

服务默认监听 `127.0.0.1`。首次启动创建节目 `G`，默认采样率为 8000 Hz，可以用 `--sample-rate` 指定首次配置。重开同一数据库时沿用已登记的配置并保留全部业务记录。`check_project.py` 由物化平台提供。直接运行原套件也可以用 `python3 -B -m unittest discover -s tests -t . -v`。回归和演示各自使用临时数据库及回环地址。

## HTTP 接口

所有请求和响应使用 JSON。素材号、片段号、修订号、条位、单号和定稿号是正整数。条位从 1 起。PCM 对象包含整数 `sample_rate`、整数 `channels`（固定为 1）、字符串 `encoding`（固定为 `pcm_s16le`）及标准 Base64 字符串 `data`。原始字节须非空且按两个字节对齐。样例见 `samples/recording.json`。

| 方法与路径 | 请求对象 | 成功响应 |
| --- | --- | --- |
| `POST /sources` | `program_id`、`description`、`pcm` | `source_id`、`program_id`、`description`、`frame_count` |
| `POST /segments` | `source_id`、`start_frame`、`end_frame` | `segment_id`、`source_id`、`program_id`、原范围及 `frame_count` |
| `POST /revisions` | `program_id`、`expected_revision_id`、`segment_ids` | `revision_id`、`program_id`、有序 `slots` |
| `GET /revisions/{id}` | 无 | 与保存时相同的固定修订 |
| `POST /voice-orders` | `revision_id`、`slots` | `order_id`、归属、`sample_rate` 与有序 `targets` |
| `POST /voice-orders/{id}/takes` | `request_id`、`parts`（原单顺序的 PCM 对象数组） | `receipt_id`、`request_id`、`take_id`、`order_id`、`revision_id` 与有序 `parts` |
| `GET /mix/{revision_id}` | 无 | `program_id`、`revision_id`、`sample_rate`、`frame_count`、`timeline`、`wav` |
| `POST /editions` | `revision_id` | `edition_id` 及固定混听结果 |
| `GET /editions/{id}` | 无 | 原签存响应 |

校样 `slots` 的每项包含 `slot`、`segment_id`、`frame_count`。工单 `targets` 和回执 `parts` 用 `position` 标记原单顺序，并记录目标 `slot` 和 `frame_count`。回执另外提供实际实收 `part_id`。混听和定稿的 `timeline` 用 `start_frame`、`end_frame` 表示输出中的半开范围，`source_kind` 为 `source` 或 `voice`，相应的 `source_id` 为源片段号或实收分段号。`wav` 为 Base64 编码的单声道、16 位 WAV。

首次保存修订传 `expected_revision_id: null`，后续传已知当前修订号。片段表允许重复引用，按请求次序生成各自的条位。配音单固定签发修订、目标顺序和长度。交件请求号在交件入口内唯一。原单及 PCM 内容相同的重投得到原首执，异参得到 409。使用新请求号可提交合格替录。混听逐个条位采用指定修订中最近成功实收的分段，缺交时采用原声。定稿按照定稿请求受理时的混听快照签存。

创建成功返回 201，读取和原样交件复领返回 200。错误响应含 `error` 字段。坏 PCM、空校样、非法帧区间或目标、分段不符返回 400，未知业务引用返回 404，过时的保存预期或交件号冲突返回 409，数据库事务失败返回 500。失败的交件不会占用请求号或改变混听，失败的定稿不会生成可领取成品。

## 样例

采编登记 `[10,11,20,21,22,30,31]`，按 `[0,2)`、`[2,5)`、`[5,7)` 取 A、B、C。编辑保存 C、B、A，配音师只为中间条位交 `[120,121,122]`。导播和展厅应听到 `[30,31,120,121,122,10,11]`，成品字节以 Base64 存在 `samples/edition.wav.b64`。演示随后交替录、另存 B、C、A 并重开服务，再核对两份修订的试听与原定稿。
