# FFmpegフィルタ対応表ドラフト

## 命名規約・前提
- ラベル: 入力`[v0]`/`[a0]`など連番。中間`[v0_bg]`, `[v0_overlay1]`, 出力`[vout]`。
- 色空間: `format=yuv420p`を基本（透過合成時は`rgba`→最終`yuv420p`）。ピクセルフォーマットはシナリオ終端で統一。
- ハードウェア: フィルタはCPU前提（`zoompan/overlay/drawtext/xfade`）。ハードウェアエンコードは出力段で`-c:v h264_nvenc`等を選択し、フィルタはCPU側で実行。

## 機能 → フィルタ/コマンド対応
| 機能 | 主フィルタ/オプション | チェーン例/備考 |
| --- | --- | --- |
| クロップ/リサイズ | `scale`, `crop`, `pad` | `scale=iw*1.0:ih*1.0`, 画角変更時は`crop=w:h:x:y` |
| パン&ズーム（Ken Burns） | `zoompan`, `scale` | `zoompan=z='between(t,0,5,1.0,1.1)':d=1:x='iw*0.5':y='ih*0.55'` など開始/終了ズームと軌道を式で指定 |
| 位置/スケール/回転アニメ | `overlay`, `rotate`, `scale` | 回転付きは`[src]rotate=theta:fillcolor=0x00000000[r1];[r1][bg]overlay=x=expr:y=expr` |
| フリーズ/ホールド | `tpad=stop_mode=clone:stop_duration=...` | シーン末尾に複写パッド |
| 背景/画面シェイク | `pad`→`crop`（sin波シフト） | `pad=...:color=0x00000000[pad];[pad]crop=...:x='expr(t)':y='expr(t)'[shake]` |
| 速度変更 | `setpts`, `atempo` | スロー`setpts=PTS/0.5`＋`atempo=0.5`（複数段で補正） |
| フェードイン/アウト | `fade=t=in|out:st: d` | 画面全体に適用 |
| クロスディゾルブ/フェード | `xfade=transition=fade|dissolve` | Finalizeで`[v0][v1]xfade=...` |
| スライドトランジション | `xfade=transition=slideleft|slideright|slideup|slidedown` | `offset`に開始時刻秒、`duration`秒 |
| ズームトランジション | `xfade=transition=zoom` | 画面ズームで場面転換 |
| テキスト（テロップ） | `drawtext` または PNG→`overlay` | 本体はPNG生成→`overlay`; シンプルなら`drawtext=fontfile=...:text='...':x=expr:y=expr:fontcolor=...:fontsize=...` |
| オーバーレイ（画像/動画） | `overlay`, `format` | 透過画像は`format=rgba`→`overlay=shortest=1` |
| ブレンドモード | `blend=all_mode=screen|multiply|addition` | 透過PNGや動画との合成 |
| 色調整 | `eq`, `hue`, `curves`, `lut3d` | プラグイン式の基本エフェクト |
| ぼかし/シャープ/ビネット | `gblur`, `unsharp`, `vignette` | 画面全体またはオーバーレイ前に適用 |
| ノイズ | `noise` | `alls=20:allf=t` 等 |
| ピクチャーインピクチャー | `scale`→`overlay` | 挿入動画を縮小・位置決め |
| 字幕バウンス | overlay生成＋`overlay` y式 | `overlay=y='base_y - amp*abs(sin(ω*t))'` |
| オーディオ音量/フェード | `volume`, `afade` | `volume=0.5,afade=t=in:st=0:d=1.0` |
| オーディオクロスフェード | `acrossfade` | `[a0][a1]acrossfade=d=1.0:c1=tri:c2=tri` |
| BGMミックス | `amix` | `[bgm][voice]amix=inputs=2:duration=shortest` |

## チェーン組み立ての型
- 背景正規化: `scale/pad/crop` → `[bg_norm]`
- クリップ本体: `[src]` →（Ken Burns/transform/rotate/scale）→ `[v_clip]`
- オーバーレイ: `[v_clip][ov1]overlay=...` → `[v_ov1]`（必要ならエフェクトを前段で）
- テキスト: PNG生成→`overlay`、または`drawtext`
- 画面効果: `[v_final]` → shake/blur → `[v_effect]`
- トランジション: `[sceneN][sceneN+1]xfade=...` → `[vout]`、音声は`acrossfade`で同offset/duration

## シーン間トランジションの基本仕様
- `transitions.wait_padding_seconds > 0` の場合、前シーンと次シーンの本編映像を直接重ねない。
- 前シーンは最後まで再生し、その終端フレームを `wait_padding_seconds` 分だけ静止保持してから、次シーン先頭との `xfade` / `acrossfade` に入る。
- トランジション境界で使用した次シーン先頭の区間は、後続の次シーン本体から消費する。これにより、OP→本編、本編→EP の境界で次シーンの冒頭音声・口パク・映像が二重化しない。
- 待ち時間付きトランジションの既定方針は「被せて短縮する」ではなく、「前シーン終了 + 静止保持 + トランジション + 次シーン継続」とする。
- `consume_next_head` で次シーン先頭を消費した後続 suffix は、stream copy ではなく再エンコードで切り出す。`-ss` + `-c copy` はキーフレーム都合で切り出し位置より前の音声を含むことがあり、短い冒頭発話がトランジション後に再度聞こえるため、現在の再エンコード方針を維持する。

## 命名パターン例（filter_complex内）
- 入力: `[v0]` `[a0]` （シーンNの映像/音声）
- 中間: `[v0_bg]`, `[v0_kb]`, `[v0_ov1]`, `[v0_text1]`
- 出力: `[v0_final]` → トランジション → `[vout]`

## 型/制約メモ
- 透過処理: 透過PNG/動画は`format=rgba`に揃え、最終で`format=yuv420p`。
- FPS/解像度: `fps`/`scale`はクリップ入口で正規化。違うFPS素材は`fps=fps_value,setpts=PTS`。
- ハードウェア: エンコードは`-c:v h264_nvenc`等を指定し、filterはCPUで実行（ffmpegの`hwupload`を使う場合は別途検討）。
