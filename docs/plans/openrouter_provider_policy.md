# OpenRouter `deepseek/deepseek-v4-flash` 供應商政策

**狀態：** 已接入 [`llm_worker/openrouter_routing.py`](../../llm_worker/openrouter_routing.py)  
**日期：** 2026-06  
**目的：** 實驗數據不被 fp4 鏡像、過貴或過慢供應商污染。

---

## 即時 API 稽核（2026-06-07）

來源：`GET https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints`

| 供應商 | tag | quant | in/out per 1M | up1d | 決策 |
|--------|-----|-------|---------------|------|------|
| Baidu | baidu/fp8 | fp8 | $0.098 / $0.197 | 99.8% | ✅ default + minimal |
| DeepInfra | deepinfra/fp4 | **fp4** | $0.10 / $0.20 | 99.4% | ❌ ignore |
| Cloudflare | cloudflare | unknown | $0.10 / $0.20 | 99.2% | ❌ 384K ctx |
| DigitalOcean | digitalocean | unknown | $0.105 / $0.21 | 91.9% | ❌ ignore |
| GMICloud | gmicloud/fp8 | fp8 | $0.112 / $0.224 | 96.2% | ❌ ignore |
| SiliconFlow | siliconflow/fp8 | fp8 | $0.13 / $0.28 | 95.7% (st=-2) | ❌ ignore（可手動加回） |
| StreamLake | streamlake | unknown | $0.133 / $0.266 | 98.2% | ✅ default |
| Alibaba | alibaba | unknown | $0.134 / $0.268 | 99.8% | ✅ default |
| Morph | morph | unknown | $0.139 / $0.278 | 97.5% | ❌ ignore |
| DeepSeek | deepseek | unknown | $0.14 / $0.28 | 100% | ✅ default + minimal |
| Parasail | parasail/fp8 | fp8 | $0.14 / $0.28 | 98.5% | ✅ default |
| AtlasCloud | atlas-cloud/fp8 | fp8 | $0.14 / $0.28 | 99.6% | ✅ default |
| AkashML | akashml/fp8 | fp8 | $0.14 / $0.28 | 96.0% | ❌ ignore |
| Novita | novita/fp8 | fp8 | $0.14 / $0.28 | 99.7% | ✅ default + minimal |
| Venice | venice | unknown | **$0.17 / $0.35** | 99.4% | ❌ ignore |

**注意：** 外部清單若寫 Baidu/AtlasCloud「在線率 9.x%」為 **小數點錯位**；API 顯示 **99.x%**。

OpenRouter endpoints API **不暴露** UI 上的 throughput (t/s)；`sort: throughput` 仍建議保留，由 OpenRouter 依其內部延遲統計排序。

---

## 程式預設

| 預設 | `only` | 說明 |
|------|--------|------|
| **default** | novita, deepseek, baidu, parasail, alibaba, streamlake, atlas-cloud | 實驗用 |
| **minimal** | novita, deepseek, baidu | 速度/價格/穩定平衡 |

另設：

- `ignore`：deepinfra, venice, gmicloud, digitalocean, cloudflare, morph, akashml, siliconflow
- `quantizations`：fp8, fp16, bf16, fp32, unknown（**排除 fp4**）
- `sort`：throughput
- `allow_fallbacks`：true（在 only 池內 fallback）

環境變數覆寫（可選，不進 `.env`  secrets）：

```bash
OPENROUTER_ROUTING_PRESET=default   # or minimal
OPENROUTER_PROVIDER_ONLY=novita,deepseek,baidu
OPENROUTER_PROVIDER_IGNORE=deepinfra,venice
OPENROUTER_QUANTIZATIONS=fp8,unknown
OPENROUTER_PROVIDER_SORT=throughput
OPENROUTER_ALLOW_FALLBACKS=true
```

---

## 稽核腳本

```bash
python3 scripts/verify_openrouter_endpoints.py
python3 scripts/verify_openrouter_endpoints.py --check-policy
```

`--check-policy` 會驗證 fp4 供應商不在 default only 池、且 DeepInfra 在 ignore 內。

---

## 與外部建議清單差異

| 項目 | 外部建議 | 本 repo 採用 |
|------|----------|--------------|
| SiliconFlow | ✅ 推薦 #2 | ❌ 預設 ignore（status=-2, up30m~94%） |
| Baidu 在線率 | 9.83% | 99.8%（API） |
| AtlasCloud 在線率 | 9.54% | 99.6%（API） |
| 極簡三家用 | novita, deepseek, baidu | ✅ `OPENROUTER_ROUTING_PRESET=minimal` |

若要恢復 SiliconFlow：`OPENROUTER_PROVIDER_ONLY=novita,siliconflow,deepseek,baidu`
