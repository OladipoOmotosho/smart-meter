# AMPds2 data dictionary and provenance

This document establishes the source contract for the smart-meter prototype before real-data ingestion. It includes the 24-hour demonstration window selected in Task 1.2.

## Dataset identity and permitted use

| Item | Recorded value |
| --- | --- |
| Dataset | *AMPds2: The Almanac of Minutely Power dataset (Version 2)* |
| Dataset DOI | [`10.7910/DVN/FIE0S4`](https://doi.org/10.7910/DVN/FIE0S4) |
| Dataverse version | 3.1, released 2020-01-16; current released version observed 2026-10-17 |
| Supporting article | S. Makonin, B. Ellert, I. V. Bajić, and F. Popowich, “Electricity, water, and natural gas consumption of a residential house in Canada from 2012 to 2014,” *Scientific Data* 3, 160037 (2016) |
| Article DOI | [`10.1038/sdata.2016.37`](https://doi.org/10.1038/sdata.2016.37) |
| Coverage | One house in Burnaby, British Columbia; 2012-04-01 00:00 America/Vancouver through 2014-03-31 23:59 America/Vancouver (1,051,200 one-minute rows) |
| Terms of use | Harvard Dataverse version 3.1 states Creative Commons Attribution 4.0 and requires citation of the supporting article. The API exposes this as custom `termsOfUse`; its standard `license` field is empty. |
| Retrieval date | **Unknown.** No independent download log was retained. Local modification timestamps are 2026-10-12 and are filesystem observations, not proof of retrieval time. |
| Intended project window | 24 complete UTC hours: `[2012-04-01T07:00:00Z, 2012-04-02T07:00:00Z)`; 1,440 source rows and sequences 0–23 |

Metadata source: the [Harvard Dataverse dataset record](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/FIE0S4) and its version metadata API, inspected 2026-10-17.

## Local source-file integrity

The source CSV files are ignored by Git and must remain unchanged. Their byte sizes and Dataverse MD5 values exactly match the files recorded in released dataset version 3.1, although the Dataverse display names use `.tab`.

| Local file | Bytes | SHA-256 (local) | MD5 (local and Dataverse v3.1) | Dataverse file record |
| --- | ---: | --- | --- | --- |
| `data/raw/Electricity_WHE.csv` | 76,575,286 | `b33fb7f1e3acf21d8dfe8876102965ec8872a5ce9142a8a400ed29f012a19964` | `f04eb317e67856248eb120fa5e733f13` | `Electricity_WHE.tab`, file ID 2741423 |
| `data/raw/Electricity_P.csv` | 77,616,811 | `c5564ba459b74b3df4ca6379769f953526ea3e00cc214f6d8bb914dd8fc11fad` | `084e5c13f07b11e6e3c6fadaf08c4d46` | `Electricity_P.tab`, file ID 2741425 |

The local article copy `docs/sdata201637.pdf` has SHA-256 `0b788bdcaf14e424e5a9ebc10b0518c3ccdbb818499b7c21ea23c43464341f3b`.

## Initial adapter: `Electricity_WHE.csv`

Exact header:

```text
unix_ts,V,I,f,DPF,APF,P,Pt,Q,Qt,S,St
```

The initial adapter will use only `unix_ts` and `P`. The remaining fields are documented so that their presence is not mistaken for permission to use them.

| Field | Meaning | Unit / representation | Source and implementation note |
| --- | --- | --- | --- |
| `unix_ts` | Timestamp of the reading | Unix time: integer seconds since 1970-01-01 00:00:00 UTC. A leading `+` is metadata, not a positive-number sign. | Supporting article, local PDF p. 6, “Data Records,” states that rows are one minute apart and timestamps increase by 60; online-only Table 4 gives the Vancouver/UTC example and the leading-plus convention. Strip and preserve the marker before integer conversion. |
| `V` | Line voltage | V, nearest 0.1 V | Supporting article, online-only Table 4. |
| `I` | Line current | A, nearest 0.1 A | Supporting article, online-only Table 4. |
| `f` | Line frequency | Hz, two decimal places | Supporting article, online-only Table 4. |
| `DPF` | Displacement power factor; cosine of voltage/current phase angle | Ratio from -1 to 1, two decimal places | Supporting article, online-only Table 4. |
| `APF` | Apparent power factor; real power divided by apparent power with harmonics included | Ratio from -1 to 1, two decimal places | Supporting article, online-only Table 4. |
| `P` | Instantaneous real (true/active) power | **W**; integer in this dataset | This is the selected power field. See “Published unit discrepancy” below. |
| `Pt` | Cumulative real energy | **Wh** | Confirmed by the authors’ AMPds measurement table and meter manual. It is not selected. Its counter semantics, reset behavior, and suitability for interval conversion have not been validated for this project, so the loader must not use it without a separate task. |
| `Q` | Instantaneous reactive power | VAR | Supporting article, online-only Table 4; meter manual specifications. |
| `Qt` | Cumulative reactive energy | VARh | Supporting article, online-only Table 4; meter manual specifications. |
| `S` | Instantaneous apparent power | VA | Supporting article, online-only Table 4; meter manual specifications. |
| `St` | Cumulative apparent energy | VAh | Supporting article, online-only Table 4; meter manual specifications. It must not be treated as utility-billed real energy merely because Table 4 makes that claim. |

### Meter identity

`WHE` means the whole-house electricity meter, equivalent to the power utility’s meter. It is a 240 V, 200 A, double-pole service. `Electricity_WHE.csv` is the full multivariate reading file for that meter. Source: supporting article Table 3 and online-only Table 4.

### Timestamp, cadence, and imputation contract

- Each row represents one meter reading at a one-minute cadence.
- The expected timestamp difference between adjacent rows is exactly 60 seconds.
- Timestamps represent UTC Unix seconds. Local civil time is `America/Vancouver`; the first timestamp, `1333263600`, is 2012-04-01 07:00:00 UTC and 2012-04-01 00:00:00 local time.
- A timestamp beginning with `+`, such as `+1333263600`, identifies a record created algorithmically because data was missing. The adapter must retain this as an imputation flag before converting the timestamp to an integer.
- The article reports that 2,029 missing **electricity readings** were filled across the electricity data collection. The local WHE file contains 1,292 plus-marked **rows**. These counts describe different scopes and must not be substituted for one another.
- The local WHE file contains 1,051,200 data rows from `1333263600` through `1396335540`. A full scan found a 60-second step throughout, no duplicate timestamp, and no reversed timestamp. This is local-file evidence, not a replacement for runtime validation.

Sources: supporting article local PDF p. 5 (“Electricity supply & metering” and missing-reading count), p. 6 (“Data Records”), and online-only Table 4.

### Published unit discrepancy for `P` and `Pt`

The 2016 article’s online-only Table 4 contains an internal metadata error: it describes `P` as real power measured in `VAR` and `Pt` as real energy measured in `VARh`. Those are reactive units and conflict with the same table’s `Q`/`Qt` definitions.

The project resolves the conflict as follows:

1. The authors’ earlier AMPds paper, Table I (“Power Measurements Captured”), defines Real Power (`P`) as W and Real Energy (`Pt`) as Wh: [author-hosted accepted manuscript](https://makonin.com/doc/EPEC_2013.pdf), DOI [`10.1109/EPEC.2013.6802949`](https://doi.org/10.1109/EPEC.2013.6802949).
2. The DENT PowerScout 18 manual supplied with the dataset lists true power separately from reactive power, with 1 watt and 1 VAR resolution (local `docs/Metering_DENTps18.pdf`, PDF p. 5, Specifications). Its register table identifies System Total True Power in kW and Reactive Power in kVAR (PDF p. 12, Table 1).
3. Electrical dimensional meaning agrees: real power uses W, reactive power uses VAR, apparent power uses VA.

Therefore the initial adapter contract is `P` = instantaneous real power in **watts**. The discrepancy must remain documented; code must not infer a unit from the header alone.

## Alternative layout: `Electricity_P.csv`

Exact header:

```text
UNIX_TS,WHE,RSE,GRE,MHE,B1E,BME,CWE,DWE,EQE,FRE,HPE,OFE,UTE,WOE,B2E,CDE,DNE,EBE,FGE,HTE,OUE,TVE,UNE
```

This file pivots the data in the other direction: each row is a timestamp, and each remaining column is the `P` real-power value for a meter or derived channel. `WHE` is therefore the whole-house real-power series in W. It is semantically related to `Electricity_WHE.csv`’s `P` field, but the schema is different (`UNIX_TS`/`WHE` rather than `unix_ts`/`P`). It requires an explicit P-file adapter and must never be selected through case-insensitive or numeric-column guessing.

The meter/channel identifiers are defined in the supporting article’s online-only Table 4. They include physical sub-meters and calculated “soft meters”: `MHE = WHE - (RSE + GRE)` and `UNE = MHE - sum(sub-meters under MHE)`. This project has not selected these derived channels for ingestion.

The local P file also has 1,051,200 rows, the same timestamp endpoints and continuous 60-second cadence, and 1,292 plus-marked timestamp rows. Its first `WHE` value equals the first WHE-file `P` value (`918`), providing a useful consistency observation but not replacing schema validation.

## Bounded demonstration selection

The demonstration input is the first 24 complete, UTC-aligned hours in `Electricity_WHE.csv`:

```text
Start, inclusive: 2012-04-01T07:00:00Z (unix_ts 1333263600)
End, exclusive:   2012-04-02T07:00:00Z (unix_ts 1333350000)
Source rows:      1,440
Hourly readings: 24, with seq 0 through 23
Meter ID:         WHE
Source field:     P (W)
Output unit:      Wh
```

This window was chosen deterministically rather than for an interesting load shape: it is the earliest contiguous block of 24 complete UTC hours in the source. Every hour contains exactly 60 unique, ordered timestamps on minute boundaries. The selected rows contain no plus-marked imputed samples, missing minutes, duplicate/reversed timestamps, negative `P` values, or incomplete boundary hours.

### Processing policy

- Treat the selection as half-open UTC hours `[start, end)`. A timestamp equal to the end belongs to the next, unselected hour.
- Exclude incomplete leading or trailing hours and count both their rows and hours in the run manifest. Never pad an edge to reach 60 samples. This selected window has zero excluded boundary rows.
- Retain source rows marked with the documented leading `+` when they otherwise validate, preserve an `imputed` flag before parsing the timestamp, and count marked samples per interval and run. Do not interpolate additional values. This selected window has zero marked samples.
- Reject the selected run on a negative `P` value and report its source row and timestamp. The initial adapter represents household consumption and has no specified export/net-generation interpretation. The full local WHE scan found zero negatives, but runtime validation remains required.
- Reject invalid, missing, or non-finite `P`; duplicate, reversed, non-minute-aligned, or internally gapped timestamps; an hour other than 60 samples; or a schema different from the exact WHE header.
- Parse `P` with exact decimal arithmetic. For each hour, estimate `Wh = sum(60 minute-level P values) / 60`, then round once to an integer using round-half-up. This assumes each recorded power value applies across its minute; it does not turn an instantaneous measurement into a directly measured energy value.
- Keep `Pt` out of this adapter. Its documented Wh unit does not establish how counter resets or differences should be handled, and the approved conversion uses `P`.
- Require `interval_minutes = 60` and a positive output limit. Other interval lengths or conversion modes require a new specification and run context.

The first selected hour contains timestamps `1333263600` through `1333267140`, has 60 samples, and has `sum(P) = 96,515 W-samples`. Its exact estimate is `96,515 / 60 = 1,608.5833… Wh`, which rounds half-up to `1,609 Wh`. The complete 24-hour selection has `sum(P) = 2,301,162 W-samples`, corresponding to an unrounded estimate of `38,352.7 Wh`. These calculations are review evidence for the selection; executable conversion tests belong to Task 4.

The alternative `Electricity_P.csv` is not selected. Its `UNIX_TS` plus meter-column layout is useful when requesting the same measurement across many meters, whereas `Electricity_WHE.csv` groups all measurement characteristics for one meter. Supporting it requires an explicit adapter so that `WHE` is mapped to real power deliberately rather than guessed from a numeric column.

## Sources and exact locations

1. Makonin et al. (2016), local `docs/sdata201637.pdf`:
   - p. 1: title, authors, dataset purpose, two-year/minute-level description;
   - p. 5: electricity metering and 2,029 filled electricity readings;
   - p. 6, “Data Records”: file naming, one row per minute, Unix seconds, 60-second increment, timestamp correction, and references to online-only Table 4.
2. [Makonin et al. (2016), PMC archival full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC4896126/), online-only Table 4: exact field names, timestamp example, plus-sign marker, WHE identity, and column descriptions.
3. Makonin et al. (2013), Table I, [author-hosted accepted manuscript](https://makonin.com/doc/EPEC_2013.pdf): `P` in W, `Pt` in Wh, `Q` in VAR, `Qt` in VARh, `S` in VA, and `St` in VAh.
4. Local `docs/Metering_DENTps18.pdf`, PDF pp. 5 and 12: measurement types/resolution and separation of true, reactive, and apparent power units.
5. [Harvard Dataverse dataset record](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/FIE0S4), released version 3.1 metadata inspected 2026-10-17: dataset DOI/version, file IDs, byte sizes, MD5 checksums, and custom terms of use.

## Task 1 contract status

Tasks 1.1–1.3 confirm the meanings and bounded selection required for the documentation gate: `unix_ts` is UTC Unix seconds with a preserved leading-plus imputation marker; samples are one minute apart; `P` is instantaneous real power in W; `WHE` identifies the whole-house meter; the demonstration uses the 24-hour half-open UTC range recorded above; and synthetic fixtures define valid, boundary and rejection behavior. Task 1.4 remains the next step and must validate this complete contract before implementation proceeds.
