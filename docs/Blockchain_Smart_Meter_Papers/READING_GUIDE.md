# Blockchain and smart-metering paper collection

Collected October 6, 2026: **10 core papers + 5 optional papers**, all saved as readable full-text PDFs.

## How the collection was selected

Started with your Google Scholar query in Chrome: `smart metering system using blockchain`, then refined to `blockchain smart meter data integrity privacy`. Supplemental searches located publisher and institutional-repository versions. Selection emphasizes your Group 8 proposal: post-ingestion tamper detection, authorized submissions, off-chain storage, on-chain commitments, batching, privacy limitations and evaluation. This is a curated set, not an exhaustive search of every Scholar result.

IEEE PDFs were saved using Chrome and existing library access. Other PDFs were downloaded from journal/publisher or institutional-repository hosts. Author manuscripts are marked below. Titles and document identities were checked against PDF front matter; every PDF was parsed and all page content streams were checked. This is relevance screening, not a full critical appraisal of the methods or reported results.

## Read first

1. **Core 09 — Asset logging:** strongest match for Merkle batching and later integrity verification.
2. **Core 10 — Multitier architecture:** closest direct smart-meter cybersecurity architecture comparison.
3. **Core 01 — GridMonitoring:** monitoring, provenance, contracts and auditing.
4. **Core 03 — BC-AMI:** authentication and the meter-to-MDMS communication boundary.
5. **Core 02 — Privacy-preserving aggregation:** distinguish privacy mechanisms from simple hash commitments.

Then read Core 05 for billing context, Core 06 for an implemented device, Core 04/08 for architecture, and Core 07 to distinguish anomaly detection from post-commitment integrity. The optional papers provide background and alternatives.

## Core papers

### 01 — GridMonitoring: Secured Sovereign Blockchain Based Monitoring on Smart Grid

Gao, Jianbin; Asamoah, Kwame Omono; Sifah, Emmanuel Boateng; Smahi, Abla; Xia, Qi; Xia, Hu; Zhang, Xiaosong; Dong, Guishan. **2018**. IEEE Access.

**Why relevant:** Blockchain monitoring, provenance, smart contracts and auditability. A direct starting reference for the project.

**Version:** Publisher PDF downloaded in Chrome.

[Open saved PDF](Core/01_GridMonitoring.pdf) · [Source](https://ieeexplore.ieee.org/document/8303679) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22GridMonitoring%3A%20Secured%20Sovereign%20Blockchain%20Based%20Monitoring%20on%20Smart%20Grid%22)

DOI: 10.1109/ACCESS.2018.2806303. 9 pages.

### 02 — Decentralized Privacy-Preserving Data Aggregation Scheme for Smart Grid Based on Blockchain

Fan, Hongbin; Liu, Yining; Zeng, Zhixin. **2020**. Sensors.

**Why relevant:** Separate privacy-preserving aggregation, signatures and integrity; useful for explaining why plain hashing is insufficient for privacy.

**Version:** Open-access publisher PDF.

[Open saved PDF](Core/02_Decentralized_Privacy_Preserving_Aggregation.pdf) · [Source](https://www.mdpi.com/1424-8220/20/18/5282) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Decentralized%20Privacy-Preserving%20Data%20Aggregation%20Scheme%20for%20Smart%20Grid%20Based%20on%20Blockchain%22)

DOI: 10.3390/s20185282. 14 pages.

### 03 — A Blockchain-Enabled Distributed Advanced Metering Infrastructure Secure Communication (BC-AMI)

Islam, Nahida; Rahman, Md. Sazzadur; Mahmud, Imtiaz; Sifat, Md. Nur Amin; Cho, You-Ze. **2022**. Applied Sciences.

**Why relevant:** AMI communication and authentication between meters, collectors and MDMS; useful for the threat model and transit-attack boundary.

**Version:** Open-access publisher PDF.

[Open saved PDF](Core/03_BC_AMI_Secure_Communication.pdf) · [Source](https://www.mdpi.com/2076-3417/12/14/7274) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22A%20Blockchain-Enabled%20Distributed%20Advanced%20Metering%20Infrastructure%20Secure%20Communication%20%28BC-AMI%29%22)

DOI: 10.3390/app12147274. 15 pages.

### 04 — Blockchain-IoT Enabled Smart Metering System

AlHawamdeh, Mariam; Tahboub, Radwan. **2023**. 2023 International Conference on Electrical and Information Technology (IEIT).

**Why relevant:** System architecture connecting meter, gateway and utility; compare a proposed design with your ingestion and audit pipeline.

**Version:** Institutional-repository author manuscript; formatting differs from the publisher version.

[Open saved PDF](Core/04_Blockchain_IoT_Enabled_Smart_Metering.pdf) · [Source](https://scholar.ppu.edu/handle/123456789/9111) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Blockchain-IoT%20Enabled%20Smart%20Metering%20System%22)

DOI: 10.1109/IEIT59852.2023.10335500. 6 pages.

### 05 — Smart Electricity Billing System Using Blockchain Technology

Aiman, Shafiq; Hassan, Suhaidi; Habbal, Adib; Rosli, Athirah; Shabli, Ahmad Hanis Mohd. **2018**. Journal of Telecommunication, Electronic and Computer Engineering, 10(2-4), 91-94.

**Why relevant:** Billing and Ethereum smart-contract context. Primarily a conceptual token/prepayment design, not proof of your tamper-detection performance.

**Version:** Journal-hosted PDF. No DOI verified; use the journal URL.

[Open saved PDF](Core/05_Smart_Electricity_Billing.pdf) · [Source](https://jtec.utem.edu.my/jtec/article/view/4323) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Smart%20Electricity%20Billing%20System%20Using%20Blockchain%20Technology%22)

4 pages.

### 06 — Blockchain-Integrated Cyber-Physical Smart Meter Design and Implementation for Secured Energy Trading in Virtual Power Plants

Kaif, A. M. A. Daiyan; Alam, Khandokar Shahjahan; Das, Sajal K.; Chen, Guo; Islam, Seyed; Muyeen, S. M.. **2025**. IEEE Transactions on Automation Science and Engineering, 22.

**Why relevant:** Implemented meter, device identity and smart-contract interaction; an implementation comparison, with a broader energy-trading/control scope than your audit prototype.

**Version:** Publisher PDF downloaded in Chrome through existing Concordia access.

[Open saved PDF](Core/06_Blockchain_Cyber_Physical_Smart_Meter.pdf) · [Source](https://ieeexplore.ieee.org/document/10984431) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Blockchain-Integrated%20Cyber-Physical%20Smart%20Meter%20Design%20and%20Implementation%20for%20Secured%20Energy%20Trading%20in%20Virtual%20Power%20Plants%22)

DOI: 10.1109/TASE.2025.3566938. 11 pages.

### 07 — Detection of False Stealthy Data Injection Attacks in Smart Meters Using Machine Learning and Blockchain Technology

Mehedi, Mohiuddin; Kabir, Abdul Aziz; Ahmed, Khandakar Rabbi; Mujtahid, Furqaan; Jamee, Sakib Salam; Rahman, Md Nayem. **2026**. Computers.

**Why relevant:** Distinguishes anomaly detection from integrity of recorded results. Use to discuss what hashing alone cannot detect; ML is outside the proposed core build.

**Version:** Open-access publisher PDF; published August 17, 2026.

[Open saved PDF](Core/07_False_Data_Injection_ML_Blockchain.pdf) · [Source](https://www.mdpi.com/2073-431X/15/8/534) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Detection%20of%20False%20Stealthy%20Data%20Injection%20Attacks%20in%20Smart%20Meters%20Using%20Machine%20Learning%20and%20Blockchain%20Technology%22)

DOI: 10.3390/computers15080534. 25 pages.

### 08 — Smart Grid Management using Blockchain: Future Scenarios and Challenges

Cioara, Tudor; Pop, Claudia; Zanc, Razvan; Anghel, Ionut; Antal, Marcel; Salomie, Ioan. **2020**. 2020 19th RoEduNet Conference: Networking in Education and Research.

**Why relevant:** Layered architecture, metering registration and smart-contract boundaries. Useful architecture context; broader than smart-meter integrity alone.

**Version:** arXiv author manuscript 2012.06256; conference publication identified in the arXiv record.

[Open saved PDF](Core/08_Smart_Grid_Management_Future_Scenarios.pdf) · [Source](https://arxiv.org/abs/2012.06256) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Smart%20Grid%20Management%20using%20Blockchain%3A%20Future%20Scenarios%20and%20Challenges%22)

DOI: 10.1109/RoEduNet51892.2020.9324874. 6 pages.

### 09 — Asset logging in the energy sector: a scalable blockchain-based data platform

Djamali, Alexander; Dossow, Patrick; Hinterstocker, Michael; Schellinger, Benjamin; Sedlmeir, Johannes; Völter, Fabiane; Willburger, Lukas. **2021**. Energy Informatics, 4(Suppl 3), 22.

**Why relevant:** Closest design reference for batching: Merkle trees/proofs, later verification, integrity, privacy and scalability. Energy asset logging is broader than household meters.

**Version:** Open-access published article from the German National Library repository.

[Open saved PDF](Core/09_Asset_Logging_Scalable_Blockchain_Data_Platform.pdf) · [Source](https://d-nb.info/1246436655) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Asset%20logging%20in%20the%20energy%20sector%3A%20a%20scalable%20blockchain-based%20data%20platform%22)

DOI: 10.1186/s42162-021-00183-3. 20 pages.

### 10 — A Novel Multitier Blockchain Architecture to Protect Data in Smart Metering Systems

Olivares-Rojas, Juan Carlos; Reyes-Archundia, Enrique; Gutiérrez-Gnecchi, José A.; Cerda-Jacobo, Jaime; González-Murueta, Johan W.. **2020**. IEEE Transactions on Engineering Management, 67(4), 1271-1284.

**Why relevant:** Direct smart-meter data-protection and scalability comparator; edge/fog/cloud tiers and a proposed consensus mechanism.

**Version:** Publisher PDF downloaded in Chrome through existing access. Online-first 2019; issue year 2020.

[Open saved PDF](Core/10_Multitier_Blockchain_Smart_Meter_Data_Protection.pdf) · [Source](https://ieeexplore.ieee.org/document/8902082) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22A%20Novel%20Multitier%20Blockchain%20Architecture%20to%20Protect%20Data%20in%20Smart%20Metering%20Systems%22)

DOI: 10.1109/TEM.2019.2950410. 14 pages.

## Optional papers

### 01 — Blockchain in Smart Grids: A Review on Different Use Cases

Alladi, Tejasvi; Chamola, Vinay; Rodrigues, Joel J. P. C.; Kozlov, Sergei A.. **2019**. Sensors.

**Why relevant:** Broad background and related-work discovery across security, privacy and trading.

**Version:** Open-access publisher PDF; review.

[Open saved PDF](Optional/01_Blockchain_Smart_Grids_Use_Cases_Review.pdf) · [Source](https://www.mdpi.com/1424-8220/19/22/4862) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Blockchain%20in%20Smart%20Grids%3A%20A%20Review%20on%20Different%20Use%20Cases%22)

DOI: 10.3390/s19224862. 25 pages.

### 02 — Privacy Preservation in Smart Meters: Current Status, Challenges and Future Directions

Kua, Jonathan; Hossain, Mohammad Belayet; Natgunanathan, Iynkaran; Xiang, Yong. **2023**. Sensors.

**Why relevant:** Privacy threats and mitigation taxonomy; supports the limitations section and avoids equating integrity with confidentiality.

**Version:** Open-access publisher PDF; review.

[Open saved PDF](Optional/02_Smart_Meter_Privacy_Review.pdf) · [Source](https://www.mdpi.com/1424-8220/23/7/3697) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Privacy%20Preservation%20in%20Smart%20Meters%3A%20Current%20Status%2C%20Challenges%20and%20Future%20Directions%22)

DOI: 10.3390/s23073697. 35 pages.

### 03 — A Survey on Key Management and Authentication Approaches in Smart Metering Systems

Abdalzaher, Mohamed S.; Fouda, Mostafa M.; Emran, Ahmed; Fadlullah, Zubair Md; Ibrahem, Mohamed I.. **2023**. Energies.

**Why relevant:** Conventional and blockchain-related alternatives for meter authentication and key management; useful baseline context.

**Version:** Open-access publisher PDF; survey.

[Open saved PDF](Optional/03_Key_Management_Authentication_Survey.pdf) · [Source](https://www.mdpi.com/1996-1073/16/5/2355) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22A%20Survey%20on%20Key%20Management%20and%20Authentication%20Approaches%20in%20Smart%20Metering%20Systems%22)

DOI: 10.3390/en16052355. 27 pages.

### 04 — Blockchain-Based Applications for Smart Grids: An Umbrella Review

Zhao, Wenbing; Qi, Quan; Zhou, Jiong; Luo, Xiong. **2023**. Energies.

**Why relevant:** Critical overview of evidence and technical inaccuracies in reviews; useful when assessing blockchain claims.

**Version:** Open-access publisher PDF; umbrella review.

[Open saved PDF](Optional/04_Blockchain_Smart_Grids_Umbrella_Review.pdf) · [Source](https://www.mdpi.com/1996-1073/16/17/6147) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22Blockchain-Based%20Applications%20for%20Smart%20Grids%3A%20An%20Umbrella%20Review%22)

DOI: 10.3390/en16176147. 35 pages.

### 05 — A Review of Cybersecurity Issues in Smart Meter-Based Energy Trading

Yang, Xingyu; Cui, Hui. **2026**. Sensors.

**Why relevant:** Recent lifecycle view of record integrity, timing, transmission, privacy and billing/settlement.

**Version:** Open-access publisher PDF; review published June 6, 2026.

[Open saved PDF](Optional/05_Cybersecurity_Smart_Meter_Energy_Trading_Review.pdf) · [Source](https://www.mdpi.com/1424-8220/26/12/3621) · [Find in Google Scholar](https://scholar.google.ca/scholar?q=%22A%20Review%20of%20Cybersecurity%20Issues%20in%20Smart%20Meter-Based%20Energy%20Trading%22)

DOI: 10.3390/s26123621. 26 pages.

## Using the references

Import `REFERENCES.ris` into Zotero or another reference manager. `PAPER_CATALOGUE.csv` and `.json` include source links, relevance, version, page count and SHA-256 checksums. Check citation formatting and author-name conventions before submitting a report. Do not copy a paper’s claims of “tamper-proof” or “privacy-preserving” without examining its attacker assumptions, trusted components and evaluation.

The downloaded papers remain unchanged. Failed download attempts are recorded under `Provenance`; no HTML error page is counted as a paper. The functional-encryption optional candidate returned 404 and was replaced by the 2026 cybersecurity review. The hardware preprint URL failed; the publisher PDF was obtained in Chrome instead.