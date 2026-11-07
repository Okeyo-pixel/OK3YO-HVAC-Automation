# OK3YO AI: HVAC & Motor Nameplate Automation Agent

An intelligent automation pipeline designed to extract, validate, and calculate industrial motor specifications from nameplate images. Built for Energy Engineers conducting ASHRAE Level II and Investment-Grade Audits, this agent streamlines Measurement & Verification (M&V) workflows by evaluating motor performance against Willdan QA/QC standards.

##  Core Features

*   **3-Tier Data Extraction Waterfall:**
    1.  **LLM Vision OCR:** Extracts primary specs (Manufacturer, Model, HP, RPM, Efficiency, Voltage, FLA, Phase) directly from raw nameplate images.
    2.  **Automated Web Scraping:** If nominal efficiency is missing, the agent queries DuckDuckGo using the extracted manufacturer and spec number to scrape technical sheets.
    3.  **Thermodynamic Calculation:** If web search fails, calculates efficiency programmatically using mathematical formulas and standardized Power Factors.
*   **Willdan Sizing Evaluation:** Automatically compares observed field data against baseline PC Calculator tools to classify retrofits as *Upsized*, *Downsized*, or *Equivalent-Sized*, checking pass/fail thresholds for required VFD speeds.
*   **Excel Integration:** Dynamically reads baseline data from `.xlsx` workbooks and appends processed inspection logs into a structured `inventory.xlsx` output.

##  Tech Stack

*   **Language:** Python 3.x
*   **AI/ML:** LLM Vision APIs (Claude/Gemini via AgentRouter)
*   **Data Processing:** `pandas`, `math`, `re`
*   **Web Scraping:** `duckduckgo_search`, `requests`
*   **Architecture:** Persistent Session Pooling, Secure Environment Variables, Robust Error Logging

##  Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/Okeyo-pixel/OK3YO-HVAC-Automation.git](https://github.com/Okeyo-pixel/OK3YO-HVAC-Automation.git)
   cd OK3YO-HVAC-Automation
