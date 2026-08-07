# 2026-08-08 CPU simple scene fast path 評価

Issue #42 の Phase 6B-8 / 6B-9 として、GPU向け simple scene fast path を CPU エンコードへ限定的に拡張する案を評価した。

## 結論

**不採用。CPUエンコードは既存の standard path を維持する。**

理由は、最小条件の固定シーンでも CPU fast path の standard/fast 比較が 90 秒以内に完了せず、性能改善を示す前に運用上の成立条件を満たさなかったため。

実験用の CPU fast-path 分岐、環境フラグ、専用 benchmark workflow / YAML / tool は master に残さない。

## 評価対象

実験では CPU fast path の候補を次の条件に限定した。

- CPU encoder
- 静止画背景
- `background.fit=stretch`
- 単一の可視 character
- scene 全体で同一 character / expression / position / scale
- `enter` / `leave` / `move` なし
- `insert` / `image_layers` / `voice_layers` なし
- screen/background effect なし
- `video_filter` なし
- PNG必須字幕なし
- 実験機能は既定OFF

当初は `talk + wait` を対象にしたが、直前の通常CIで CPU standard path の `wait` clip が一度だけ 600 秒 timeout したため、比較ノイズを除く目的で最終評価は **talk-only** に縮小した。

## 最終固定条件

- GitHub Actions `ubuntu-latest`
- Python 3.14.6
- runtime lock 固定FFmpeg
- `--hw-encoder cpu`
- `--quality speed`
- `--jobs 1`
- `--no-cache`
- `--no-voice`
- 320x180
- 10 fps
- 1.2 秒 talk-only scene
- 静止画背景 + 単一静的 character
- standard 1回 → fast 1回の比較ペア
- 上位 workflow から `timeout 90s` を適用

## 結果

Performance Smoke run `31205829571` の CPU standard/fast 比較 step は、90秒の上限で終了し `exit code 124` となった。

- benchmark結果JSON: 未生成
- benchmark artifact: 未生成
- 同一headの通常CI run `31205828460`: success
- 直前の複数回試行でも CPU比較stepが長時間継続し、通常の fixed cold/warm benchmark より明確に重かった

比較対象として、PR #66 時点の既存 fixed cold/warm CPU smoke は次の実測だった。

| trial | elapsed | VideoPhase | ffmpeg | ffprobe |
|---|---:|---:|---:|---:|
| cold | 6.473 s | 5043.0 ms | 19 | 16 |
| warm1 | 0.806 s | 56.3 ms | 8 | 4 |
| warm2 | 0.818 s | 57.0 ms | 8 | 4 |

CPU fast path は、より小さい 1.2 秒固定シーンの standard/fast 1ペアすら 90 秒以内に評価完了できなかった。したがって「wall time / VideoPhase とも standard 比 90% 以下」という採用基準を評価可能な状態に到達していない。

## 判断

採用条件:

1. A/V・字幕・character timing の同等性
2. cold path の意味のある改善
3. fallback の再現性
4. 追加複雑性を説明できること

今回の実験は 2 を満たさず、さらに比較自体の実行コストが高い。CPU専用分岐を残すと eligibility / wait handling / benchmark / CI の保守対象が増えるため、費用対効果が成立しない。

よって以下を採用する。

- Phase 6B の責務分割は維持する
- GPU simple scene fast path は既存条件のまま維持する
- CPU encoder は従来どおり `cpu_encoder` で fast path を即時拒否する
- CPU fast path 実験コードは残さない
- CPU経路の次の性能改善は cache / probe / ClipRenderer 等、実測上の既存ボトルネック側から行う

## 関連

- Issue #42
- PR #63: scene preparation split
- PR #64: pure fast-path eligibility
- PR #65: character planning split
- PR #66: plan / graph / executor split
- PR #67: CPU評価と不採用記録
