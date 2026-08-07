# 2026-08-07 Issue #44 回帰検証

## 対象

2026-08-07にmasterへ統合した性能・診断変更群を、PR #46のpull request Actionsで一括検証した。

検証head: `6e4c7611cb5786ed386e350b0bd3ca383e6ca112`

## Actions

| Workflow | Run | 結果 |
|---|---:|---|
| CI | `31135886560` | success |
| Performance Smoke | `31135886525` | success |

CIで以下がすべて成功した。

- runtime lock検証
- Python 3.14.6環境構築
- source metrics生成
- unit tests
- FFmpeg integration tests
- wheel / sdist build
- clean wheel install
- CPU render smoke
- no-voice media reproducibility

## CI中に検出・修正した回帰

最初のCI run `31135648506`ではunit testが5件失敗した。

### AudioDurationCacheProxyのdelegate互換

WAV header読取失敗後、既存CacheManager互換実装へ常に`caller=`を渡していた。`caller`引数を持たないstub・旧実装で`TypeError`になった。

修正:

- `caller is None`では従来どおりpathだけを渡す
- `caller`非対応による`TypeError`だけ、pathのみで再試行する
- delegate内部から発生した別の`TypeError`は握り潰さない

### Run Base safety guardの責務境界

安全層が`_render_scene_internal`をoverrideし、標準描画オーケストレーションの定義元が`scene_standard_renderer.py`ではなくなっていた。

修正:

- safety mixinはeffective `scene_cp`の決定だけを担当
- facadeが標準描画呼出直前にguardを適用
- `_render_scene_internal`の所有権を`SceneStandardRendererMixin`へ戻した

## CPU smoke

| 項目 | 値 |
|---|---:|
| Python | 3.14.6 |
| FFmpeg | n8.1.2-21-gce3c09c101-20260630 |
| 出力 | 320x180 / 10 fps / H.264 + AAC |
| container duration | 5.365 s |
| video duration | 5.300 s |
| audio duration | 5.269333 s |
| video start | 0.200 s |
| audio start | 0.135 s |
| wall time | 4.543 s |
| VideoPhase | 3707.8 ms |
| AudioPhase | 351.2 ms |
| FinalizePhase | 106.4 ms |
| ffmpeg calls | 22 |
| ffprobe calls | 19 |
| A/V警告 | 0 |

## 再現性

`no_voice=true`、`hw_encoder=cpu`で2回生成し、以下が一致した。

- video framemd5 SHA-256
- decoded audio PCM SHA-256
- Markdown / CSV / SRT / ASS sidecar SHA-256
- ffprobe stream/format情報

結果: `status=pass`、差分0件。

## cold / warm固定ベンチ

条件:

- script: `scripts/smoke_minimal.yaml`
- `--hw-encoder cpu`
- `--quality speed`
- `--jobs 1`
- `--no-voice`
- coldは`--cache-refresh`

| 指標 | cold | warm1 | warm2 |
|---|---:|---:|---:|
| elapsed | 6.735 s | 0.773 s | 0.759 s |
| VideoPhase | 5187.6 ms | 55.0 ms | 55.5 ms |
| AudioPhase | 446.1 ms | 360.6 ms | 344.4 ms |
| FinalizePhase | 99.4 ms | 14.4 ms | 28.6 ms |
| ffmpeg calls | 22 | 8 | 8 |
| ffprobe calls | 19 | 4 | 4 |
| cache miss | 27 | 7 | 5 |
| line clips | 4 | 0 | 0 |
| subtitle burn | 236.0 ms | 0 ms | 0 ms |
| A/V警告 | 0 | 0 | 0 |

比較:

- warm1 / cold: `0.114774`
- warm2 / cold: `0.112695`
- warm2 / warm1: `0.981889`
- coldとwarmの出力サイズはすべて`105684 bytes`

判定:

- scene cache HIT時にline clipとsubtitle burnは実行されていない
- warmのVideoPhaseは約55 msで安定
- warmでもAudioPhaseが約0.34〜0.36秒残り、次の固定費分析対象
- warmでもffmpeg 8回・ffprobe 4回が残るため、CacheManager/Finalize内部改善の余地あり

## source metrics

| 指標 | 値 |
|---|---:|
| Python files | 202 |
| 500行超ファイル | 19 |
| 80行超関数 | 75 |
| `scene_standard_renderer.py` | 1019行 |
| `_render_scene_internal` | 996行 |

構造改善の次タスクはIssue #33およびIssue #39を優先する。

## 成果物

- CI artifact: `smoke-python-3.14.6-render` (`8977927938`)
- package artifact: `packages-python-3.14.6` (`8977922368`)
- benchmark artifact: `cold-warm-python-3.14.6` (`8977918970`)
