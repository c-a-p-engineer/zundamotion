# 高速化の履歴と回帰防止メモ

このドキュメントは、Zundamotion を再度高速化するときに「以前に遅くなった変更」を繰り返さないための記録です。

結論から書くと、CPU 経路では「大きな 1 本の filter graph にまとめれば速い」とは限りません。実測しない最適化は簡単に悪化します。

## 目的

- 何をやったら遅くなったかを残す
- 何をやったら速くなったかを残す
- 再計測時の前提条件を固定する
- どこまでが現実的な改善余地かを明確にする

## 先に結論

- CPU では、巨大な scene fast path は逆に遅くなった
- CPU では、`clip_workers=6` と過大な `filter_threads` は遅かった
- VOICEVOX の長い再試行は全体時間を大きく悪化させた
- 完成版字幕は `PNG overlay` より `ASS/libass` の方が速かった
- `cache_refresh` が同一キーを何度も消す実装は無駄だった
- いまの CPU 経路の残ボトルネックは主に `VOICEVOX` と最終字幕焼き込み

## 遅くなった変更

### 1. CPU で simple scene fast path を有効化した

内容:
- 「1 シーン 1 FFmpeg」に寄せる fast path を CPU でも使った

結果:
- `diiva_company_intro` では逆に遅くなった
- CPU は巨大な `filter_complex` 1 本より、行クリップを 2 並列で回した方が安定して速かった

原因:
- 字幕、立ち絵、顔差分、背景処理を 1 本へ詰め込むと、CPU フィルタ処理が重くなりすぎた

今後のルール:
- `scene fast path` は GPU 利用時だけ試す
- CPU ではデフォルトで無効のままにする
- CPU で再挑戦する場合は、必ず同じ台本でベンチマークしてから有効化する

### 2. CPU で `clip_workers` と FFmpeg フィルタスレッドを上げすぎた

内容:
- CPU 経路でも `clip_workers=6`
- `filter_threads=12`, `filter_complex_threads=12`

結果:
- 並列しすぎて逆に遅くなった
- ログでは CPU オーバーレイ系のクリップが悪化した

原因:
- 立ち絵・顔差分・字幕のあるクリップは CPU フィルタ負荷が高く、プロセス並列とフィルタ並列の両方を増やすと oversubscription になる

今後のルール:
- CPU オーバーレイ中心では `clip_workers=2` を基準にする
- CPU では `filter_threads` / `filter_complex_threads` は控えめにする
- `hw_kind is None` を CPU-bound として扱う

### 3. VOICEVOX のリトライを重くしすぎた

内容:
- 多段の指数バックオフで長時間待つ構成

結果:
- 接続不安定時に `AudioPhase` が極端に長くなった
- 実際に `143.95s` まで膨らんだログがあった

原因:
- 失敗した合成を長時間待ち続けた

今後のルール:
- リトライ回数は少なめに抑える
- 待機時間は短く切る
- 不安定時は早めに silent fallback へ切り替える

### 4. `no_sub` を既定で作った

内容:
- 完成版に加えて `*_no_sub.mp4` も毎回作る

結果:
- Finalize/BGM の追加処理が増えた
- 利用しない場合は純粋な無駄だった

今後のルール:
- `system.generate_no_sub_video` は既定で `false`
- 本当に必要なときだけ opt-in

### 5. `cache_refresh` で同じキーを何度も消した

内容:
- `face_overlay.png` など同じキャッシュキーを同一実行中に何度も削除・再生成した
- `get_cached_path()` 側では scene キャッシュが生き残る抜け道もあった

結果:
- コールド計測のつもりでも無駄な再生成が増えた
- 逆に scene キャッシュだけ残って測定が歪むケースもあった

今後のルール:
- `cache_refresh` は「1 実行につき同一キー 1 回だけ無効化」
- `get_or_create()` と `get_cached_path()` の両方で `cache_refresh` を尊重する
- 同一キーの並列生成は 1 本に集約する

## 速くなった変更

### 1. 完成版字幕を `ASS/libass` 優先にした

内容:
- 最終字幕焼き込みを PNG 連続 overlay から `ASS/libass` 優先へ変更

効果:
- 最終字幕合成のコストを削減
- 完成版字幕の経路がシンプルになった

ルール:
- 軽量な字幕ボックスは `ASS/libass`
- 角丸や枠線や背景画像を含む装飾付き字幕は `PNG`

### 2. 完成版の前景/字幕合成を単発ジョブ向けスレッド数にした

内容:
- 行クリップ用の `clip_workers` に引っ張られず、最終焼き込みは単発 FFmpeg としてスレッド数を決定

効果:
- 最終字幕焼き込みのスレッド不足を回避
- CPU での最終段が少し短くなった

ルール:
- `apply_foreground_overlays()`
- `apply_overlays()`
- `apply_subtitle_overlays()`

これらの最終合成は単発ジョブとして扱う

### 3. 字幕 PNG のプロセスプールを共有した

内容:
- scene ごとに `SubtitlePNGRenderer` を作り直さないようにした

効果:
- 字幕 PNG ワーカーの起動コストを削減

### 4. 音声生成を先行並列化したが、並列度は 2 を基準にした

内容:
- AudioPhase の逐次実行をやめ、順序維持のまま先行並列化
- ただし `auto` の既定上限は 2

効果:
- 安定しているときの `AudioPhase` を短縮
- 3 以上に上げて不安定化するケースを避けた

### 5. CPU 経路のスレッド判定を修正した

内容:
- `hw_kind is None` を CPU-bound として扱うよう修正

効果:
- CPU クリップが `threads=6 / filter_threads=4 / filter_complex_threads=4` へ落ち着いた
- 過剰なフィルタスレッドを避けられた

### 6. `cache_refresh` の実効性を直した

内容:
- scene キャッシュも含めて正しく再生成
- 同一キーの並列生成を抑止

効果:
- コールド計測の再現性が上がった
- `face_overlay` の無駄な再生成が減った

## ベンチマーク時の手順

### コールド計測

どちらかを使う:

```bash
rm -rf cache/*
```

または

```bash
python -m zundamotion.main ... --cache-refresh
```

注意:
- `--cache-refresh` は現在、scene キャッシュも含めて再生成される
- 比較条件を揃えるなら `cache/` 削除の方が分かりやすい

### 推奨比較コマンド

音声なし:

```bash
python -m zundamotion.main scripts/diiva_company_intro.yaml \
  -o output/diiva_company_intro.mp4 \
  --quality speed \
  --jobs auto \
  --hw-encoder cpu \
  --no-voice \
  --log-kv
```

音声あり:

```bash
python -m zundamotion.main scripts/diiva_company_intro.yaml \
  -o output/diiva_company_intro.mp4 \
  --quality speed \
  --jobs auto \
  --hw-encoder cpu \
  --log-kv
```

### 比較時に見るべき値

- `AudioPhase.run`
- `VideoPhase.run`
- `FinalizePhase.run`
- 各クリップの `Finished clip ... in Xs`
- 最終字幕焼き込みの所要時間
- `VOICEVOX synthesis failed ...`
- `clip_workers` / `threads` / `filter_threads`

## 参考ベースライン

2026-03-27 時点:

- 遅かった実行例: `456.14s`
  - `AudioPhase: 143.95s`
  - `VideoPhase: 306.65s`
- 以前のコールド実行: `296.01s`
- 改善後のコールド `--no-voice`: `98.02s`
  - `AudioPhase: 1.34s`
  - `VideoPhase: 94.49s`
- 改善後のコールド音声あり: `233.74s`
  - `AudioPhase: 98.14s`
  - `VideoPhase: 133.05s`

## 現時点での打ち止めライン

CPU 経路では、レンダラー内部だけでさらに大きく縮める余地は小さいです。

次の大きな改善が必要なら、候補は次の 3 つです。

- GPU 実機で scene fast path を本格運用する
- より安定した高速 TTS に切り替える
- 「1 シーン 1 render graph」を本格実装する

逆に、以下はもう安易にやらないこと:

- CPU で巨大 scene fast path を既定有効化
- CPU で `clip_workers` を大きく戻す
- VOICEVOX の長い待機リトライを増やす
- `no_sub` を既定出力へ戻す
