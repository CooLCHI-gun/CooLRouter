# CooLRouter

<p align="center">
  <img src="assets/logo.svg" alt="CooLRouter 標誌 — 路由節點圖示" width="100">
</p>

<h1 align="center">CooLRouter</h1>

<p align="center"><strong>該委派哪個能力——以及，如何避免讓「聽起來很肯定的結果」買走你的信任？</strong><br>
一套以意圖為導向、分層路由的人工智慧代理運行層。負責任地委派直覺，並清楚界定哪些部分不應委派。</p>

<p align="center">
  <a href="README.md"><strong>English →</strong></a>
</p>

<p align="center">
  <code>第 0 級 · 本機</code> · <code>第 1 級 · 雲端</code> · <code>第 2 級 · 研究</code> · <code>第 3 級 · 趨勢</code> · <code>第 4 級 · 自主</code> · <code>第 5 級 · 批判</code>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/local--first-Ollama--emerald" alt="local-first">
  <img src="https://img.shields.io/badge/cost--aware-intent--guided--routing-blue" alt="cost-aware">
  <img src="https://img.shields.io/badge/verify--before--trust-rose" alt="verify-before-trust">
  <img src="https://img.shields.io/badge/no--PII-redacted-slate" alt="PII-safe">
</p>

<p align="center">
  <img src="assets/demo-routing.gif" alt="CooLRouter —— 一個任務走過路由器：decide、dispatch、deliver" width="900">
</p>

<p align="center">
  <a href="#為何需要-coolrouter">為何需要</a> · <a href="#六個等級">六個等級</a> · <a href="#路由如何運作">路由機制</a> · <a href="#型別化決策jev">Jev</a> · <a href="#防護機制">防護機制</a> · <a href="#部署">部署</a> · <a href="#目錄結構">目錄結構</a> · <a href="#限制說明">限制</a>
</p>

> **能以最低成本完成任務、且經得起驗證的模型，就是正確的模型。**
> 一個請求 → 一個意圖 → 一個能力等級。成本控制是原則，而非事後對帳。

## 為何需要 CooLRouter

「用一套大型模型處理所有事情」看似簡單，實際上既耗費預算，也欠缺智慧。分類、格式化、摘要、簡短修復等簡單需求，並不需要深層推論。工作應依照**意圖**分派，而非依照目前安裝了哪個模型。CooLRouter 就是負責在每個請求接觸任何模型之前，先做出這項決策的層級。

本專案基於三項信念：

- **依意圖，而非依模型** —— 路由器根據「任務需要什麼能力」來分派，而不是根據已安裝什麼。
- **成本也是正確性的一部分** —— 昂貴的答案並不「更好」，只是更貴。有意義的指標是「能驗證完成的最低成本方案」，而非「令人印象最深刻的方案」。
- **先驗證，再信任** —— 一次成功的工具呼叫是驗證的**起點**，並非終點。

## 六個等級

| 等級 | 引擎 | 適用 | 成本 / 隱私 |
|:--|:--|:--|:--|
| **第 0 級 · 本機** | 本機小模型 | 分類、格式化、短編輯、路由 | 約 $0 · 完全本機 |
| **第 1 級 · 雲端** | 前沿模型（計量收費） | 深度推論、長上下文、視覺 | 計量 · 遠端 |
| **第 2 級 · 研究** | 檢索增強（RAG）+ 引用 | 論文、來源、有依據的綜合 | 以檢索計 |
| **第 3 級 · 趨勢** | 即時網路檢索 | 熱門話題、即時資訊流、新鮮度 | 即時 · 以網路為依據 |
| **第 4 級 · 自主** | 自主、多步驟 | 自維持工作流程 | 以編排計 |
| **第 5 級 · 批判** | 自我評估、反向審查 | 在交付前質疑成果；執行防護機制 | 以防護計 |

研究級與趨勢級之所以存在，是因為**答案所需的「依據類型」本身即路由訊號**。學術問題要求出處；時事問題要求時效。兩者都無法簡化為一般推論任務。階梯頂端的自主級與批判級則源於：工作未必只有單一答案 —— 有時它是一個**過程**，有時它需要在產出後被**質疑**。

## 路由如何運作

```
請求 → 意圖 → 能力等級 → 防護機制 → 執行 → 佐證 → 輸出
```

<p align="center">
  <img src="assets/router-decision-chain.svg" alt="CooLRouter 決策鏈：classify、privacy gate、typed-decision guards、dispatch + VRAM、emit" width="900">
</p>

路由核心的實作收錄於 [`router/router-proxy.py`](router/router-proxy.py)；完整的技術說明見 [`docs/router-architecture.md`](docs/router-architecture.md)——包含架構圖、13 階段決策鏈（含行號）、tier 表、回應契約、護欄一覽與已知缺陷清單。

三個組件的權重高於任何單一模型：

1. **意圖路由器** —— 在任何模型接觸請求之前，先根據請求內容決定「在哪裡處理」。成本控制是原則，而非事後對帳。
2. **執行層** —— 一個不花俏的迴圈。它呼叫相關技能、透過受控作用的客戶端呼叫真實工具，並且在取得驗證之前，不會宣稱完成。精巧之處在於技能，而非迴圈本身。
3. **技能庫** —— 程序性記憶。一個條目是某類重複性工作的操作方法，只在相關時才載入，一旦出現偏差或缺陷就會被修訂。複利式的學習累積在此。

> 註：**能力等級**（faculty）在此指「該等級加上為回答請求所需的一組具體技能與工具」。

工具的引入是有節制且範圍受控的：外部能力經由情境伺服器提供，命令列工具以精簡方式導入（`npx`、`pip`），而非逐步堆疊成龐雜的介面。

## 型別化決策（Jev）

決策鏈中有一段並非 chat model。`typesafe/jev-1.13` 回傳的是**型別化**答案 — `Choice`、`Score` 或
`Noul` — 附帶已校準的機率，每次決策約 **$0.000027**、耗時 0.34–0.48 秒。路由器因此可以「採用一個決策」，
而不必解析一句自然語言。

它出現的位置，以及刻意不出現的位置：

| 用途 | 提出的問題 | 路由器如何使用答案 |
|:--|:--|:--|
| `len_class` | 這個回答應該多長？ | 決定 local tier 的輸出上限（one-line / short / detailed → 96 / 320 / 1200 tokens） |
| world-knowledge guard | 是否需要模型無法持有的外部事實？ | 命中則把 `local` **向上**移到雲端 tier，避免小模型被要求回憶事實而虛構 |
| citation guard | 這個說法是否需要來源？ | 命中則把請求移到 research tier |

以上是量測結果，不是假設 — 在 164 筆實際請求中：guards 只觸發 **5 次（3%）**；80 筆 local 請求中有 61 筆
付了長度分類費用；而 13 筆因私隱被強制 local 的請求**完全沒有付費**，因為 privacy guard 先於 Jev 決定。

實作上有三點直接由這次量測得出：

- **一次呼叫，而非三次。** 長度分類與兩個 guard 已合併為單一決策呼叫（`_jev_decide`）；原設計在「本應最快」
  的 tier 上做了兩次連續往返。
- **純算術不會經過它。** `2+2` 在程式碼中直接短路（`guard=['pure_calc:no_escalation']`），計算成本為零次雲端呼叫。
- **它只能把請求往上移。** guard 可以把 `local` 提升到雲端；沒有任何路徑能把雲端決策降級，因此 tier 分工
  不會被分類器打亂。

以下是踩過的坑，也是最值得抄走的部分：

- **`Choice` 只回傳一個選項。** 要它從四個項目中挑出「耐久的」，得到 0.56 / 0.42、信心 0.43 — 無法使用。
  應改為每個項目問一次 `Noul`。
- **不要用它判斷語言或編碼。** 一段明顯的繁體中文輸入，在「是否為繁體中文？」上只得 0.47。
- **它讀得很字面。** 一份清盤呈請在「是否提及官方來源」上只得 0.2，直到把判準寫成明確條件才正確。
- **算術與日期留在程式碼裡。** TypeSafe 自己列出的鋸齒邊緣（數學、日期比較、間接指涉、大量無關狀態、矛盾判準）是準確的。
- **它是雲端呼叫，因此永遠不會擋在私隱流量前面。** 型別化決策模型會離開本機；privacy guard 先跑並 fail-closed
  到 local tier，該路徑完全不會諮詢 Jev。
- **沒有量測就不要宣稱。** `/healthz` 回報 `jev_calls`，每個回應都帶 `x-guard`，所以「guards 很便宜」是一個數字，不是信念。

## 防護機制

在各等級之下，列有一個每個請求在可被稱為「完成」之前必須滿足的條件：

> **永遠不要相信自我報告。從多個角度加以佐證。以實際運行的系統進行測試。**

視覺感知（圖片、影格、截圖）被視為路由提示，而非事後補救，並且與任何文字採用相同的驗證標準。

## 刻意不採用的方案

每個安排都有一個更光鮮的替代方案——基於成本或誠實，通常加以拒絕。

- *不採用單體架構。* 精簡迴圈搭配一組精準技能，更易推理、維修成本更低。
- *不自行託管前沿模型。* 本機等級的存在是為了隱私與經濟，而非因為前沿模型可以在家複製。
- *不「讓位給最大模型」。* 那通常是最貴的途徑，也很少是最合適的。
- *不盲目自動化。* 系統只在確定性高且風險低的工作上無人運行；凡具實質後果的工作，一律先由人類檢視。

## 部署

```sh
cp deploy/.env.example .env     # 只填入你實際持有的 key
sh deploy/install.sh            # Linux / macOS（Windows 用 ./deploy/install.ps1）
```

路由核心是單一 Python 檔案，沒有任何第三方依賴，因此「部署」等同「執行它」。[`deploy/`](deploy/)
收錄各種包裝：兩個平台的安裝腳本、`systemd --user` unit、容器路徑，以及把 agent 接到它上面的設定片段。

回應會把路由決策一併帶回（`x-route`、`x-leg`、`x-ms`、`x-guard` 等，位於回應 body 的頂層欄位），
因此每個請求「為何被送往該處」都有跡可循。完整契約見 [`docs/router-architecture.zh-TW.md`](docs/router-architecture.zh-TW.md)。

## 目錄結構

```
.
├── assets/        demo-routing.gif（三幕演示）· 架構圖 · 決策鏈圖 · 社交影片 · 標誌
├── deploy/        install.sh · install.ps1 · Dockerfile · compose · systemd unit · Hermes 設定與 plugin
├── config/        環境配置範例（數值已遮蔽，保留結構）
├── router/        router-proxy.py —— 路由核心，附說明與測試
├── skills/        技能條目範例——呈現模式，非實際內容
├── docs/          router-architecture.md（深入技術說明）· sonar review · 工作筆記
├── README.md      英文正本
├── README-zh-TW.md  本檔（繁體中文導讀）
└── LICENSE        MIT
```

動畫素材皆為程式生成：`demo-routing.gif`（20 幀、12.4 秒，示範一個任務走過 decide → dispatch → deliver）、`social.mp4`（7 秒循環）、`promo.mp4`（12 秒 Remotion 電影式宣傳）、`architecture.svg`（六級架構圖）、`router-decision-chain.svg`（決策鏈圖，依設計規格生成）。生成器位於 `assets/_gen_*.py`（已加入 .gitignore）；`promo.mp4` 的原始碼是完整的 Remotion 專案，位於 `promo/`。

## 限制說明

- **個人化工具** —— 針對單一機器與單一工作流程而設計，並非通用儀器。
- **受硬體限制** —— 本機等級需要足夠的硬體；若無，則收縮至分類與格式化。架構保持不變，只是本機等級的範圍縮小。
- **依賴供應商** —— 雲端與趨勢等級依賴遠端供應商，因此此安排偏好簡潔，而非跨供應商可攜性。
- **誠實重於數字** —— 我只報導能佐證的內容。若某個數字需要推測，你會看到一則陳述代替。

## 公開的原因

我每天與代理人並肩工作，其誠實面貌——分派、驗證紀律、前進習慣——值得記錄下來，給那些好奇但尚未信服的人。這不是一篇主張系統取代工程師的文章，而是一個人在「讓代理人變得有用、且不任其變成負債」這件事上的筆記。

它與 [**CooLEVAL**](https://github.com/CooLCHI-gun/CooLEVAL) 並存——那是建立於此同一配置之上的可靠性儀器。CooLEVAL 是**量測**；這裡是被量測的**工作空間**。

## 授權

MIT — 見 [LICENSE](LICENSE)。

<p align="center"><i>不含原始配置、不含個人資料、不含專有工作。</i></p>
