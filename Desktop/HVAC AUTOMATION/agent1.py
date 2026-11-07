import base64
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from duckduckgo_search import DDGS

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# --- Configuration & Constants ---
API_KEY = os.getenv("AGENT_ROUTER_API_KEY", "YOUR_LOCAL_API_KEY_HERE")
API_URL = "https://agentrouter.org/v1/chat/completions"

BASE_DIR = Path(__file__).parent
IMAGE_DIR = BASE_DIR / "NAMEPLATES"
SPEEDS_FILE = BASE_DIR / "ObservedMotorSpeeds.txt"
PC_TOOL_FILE = BASE_DIR / "PC calculations tool.xlsx"
OUTPUT_FILE = BASE_DIR / "inventory.xlsx"


# --- Helper Functions ---
def encode_image(image_path: Path) -> str:
    """Converts a binary image file into a Base64 text string."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

def extract_number(value: Any) -> Optional[float]:
    """Isolates and extracts float values from messy text strings."""
    if value is None:
        return None
    try:
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", str(value))
        return float(numbers[0]) if numbers else None
    except (ValueError, TypeError):
        return None

def normalize_efficiency(eff: Optional[float]) -> Optional[float]:
    """Normalizes percentage inputs to decimal format (e.g., 94.5 -> 0.945)."""
    if eff is None:
        return None
    return round(eff / 100, 3) if eff > 1 else round(eff, 3)

def get_willdan_pf(hp: Optional[float]) -> Optional[float]:
    """Assigns standardized Willdan full-load Power Factor based on Motor HP."""
    if hp is None:
        return None
    
    if 0 < hp <= 5:
        return 0.84
    elif 5 < hp <= 20:
        return 0.86
    elif 20 < hp <= 100:
        return 0.89
    elif 100 < hp <= 300: 
        return 0.91
    return None

def load_observed_speeds(filepath: Path) -> Dict[str, float]:
    """Dynamically loads observed motor speeds from a local text file."""
    speeds: Dict[str, float] = {}
    if not filepath.exists():
        logger.warning(f"'{filepath.name}' not found. Defaulting all speeds to 0.70.")
        return speeds
        
    with open(filepath, 'r', encoding="utf-8") as f:
        for line in f:
            parts = re.split(r'[:=\t]+', line.strip())
            if len(parts) >= 2:
                motor_id = parts[0].strip()
                try:
                    speed_val = parts[1].strip().replace('%', '')
                    speed = float(speed_val)
                    speeds[motor_id] = speed / 100.0 if speed > 1 else speed
                except ValueError:
                    continue
    return speeds

def load_pc_calculator_data(filepath: Path) -> Dict[str, Dict[str, Any]]:
    """Loads PC proposed claims from the EC Motors Excel sheet."""
    if not filepath.exists():
        logger.warning(f"'{filepath.name}' not found. Proceeding without PC comparison.")
        return {}
    
    try:
        df = pd.read_excel(filepath, sheet_name="EC Motors")
        pc_records = {}
        for _, row in df.iterrows():
            motor_id = row.iloc[1]  # Column B: Motor ID
            if pd.notna(motor_id):
                pc_records[str(motor_id).strip()] = {
                    "PC_Existing_HP": row.iloc[13],
                    "PC_Proposed_HP": row.iloc[27],
                    "PC_RPM": row.iloc[16],
                    "PC_Efficiency": row.iloc[20]
                }
        return pc_records
    except Exception as e:
        logger.error(f"Failed to read PC calculator tool: {e}")
        return {}


# --- External API Interactions ---
def ask_llm(messages: List[Dict[str, Any]], session: requests.Session) -> Dict[str, Any]:
    """Handles API requests to the LLM router using a persistent session."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "Originator": "codex_cli_rs",
        "User-Agent": "codex_cli_rs/0.101.0 (Mac OS 26.0.1; arm64) Apple_Terminal/464",
        "Version": "0.101.0"
    }
    payload = {
        "model": "claude-opus-4-8", 
        "messages": messages,
        "max_tokens": 600
    }
    
    try:
        response = session.post(API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_data = response.json()
    except requests.RequestException as e:
        logger.error(f"LLM API Request failed: {e}")
        return {}
    
    if 'choices' not in response_data:
        logger.error(f"Unexpected API response format: {response_data}")
        return {} 
    
    raw_content = response_data['choices'][0]['message']['content']
    
    # Strip markdown code blocks if present
    if "```json" in raw_content:
        raw_content = raw_content.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_content:
        raw_content = raw_content.split("```")[1].split("```")[0].strip()
        
    try:
        start_idx = raw_content.index('{')
        end_idx = raw_content.rindex('}') + 1
        return json.loads(raw_content[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError):
        logger.warning("Failed to parse LLM response as JSON.")
        return {"Raw_Text": raw_content}

def extract_motor_data(image_path: Path, session: requests.Session) -> Dict[str, Any]:
    """Uses LLM Vision to extract technical specs from a nameplate image."""
    base64_image = encode_image(image_path)
    mime_type = "image/png" if image_path.suffix.lower() == '.png' else "image/jpeg"
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Analyze this industrial motor nameplate carefully. Extract as many visible parameters as possible. "
                        "Look for Manufacturer, Model Number, Catalog Number, Specification Number (Spec_No), HP, RPM, Efficiency, Voltage, FLA, and Phase. "
                        "If any parameter is missing or illegible, return null for that value. "
                        "CRITICAL: Return ONLY a valid JSON object with these exact keys: "
                        "'Manufacturer', 'Spec_No', 'HP', 'RPM', 'Efficiency', 'Voltage', 'FLA', 'Phase'."
                    )
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                }
            ]
        }
    ]
    return ask_llm(messages, session)

def search_efficiency_online(manufacturer: str, spec_no: str, session: requests.Session) -> Optional[float]:
    """Queries DuckDuckGo to find nominal efficiency when missing from nameplate."""
    if not manufacturer and not spec_no:
        return None
        
    search_term = f"{manufacturer or ''} {spec_no or ''}".strip()
    logger.info(f"Initiating web search for motor efficiency: '{search_term}'...")
    
    query = f"{search_term} motor nominal efficiency technical specifications"
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            
        if not results:
            return None
            
        snippets = " ".join([r.get('body', '') for r in results])
        messages = [{
            "role": "user",
            "content": f"Here are web search results for a motor ({search_term}): {snippets}. Extract the nominal efficiency percentage. Return ONLY a JSON object with the key 'Efficiency'. If not found, return null."
        }]
        
        llm_response = ask_llm(messages, session)
        return extract_number(llm_response.get("Efficiency"))
        
    except Exception as e:
        logger.error(f"Web search failed for '{search_term}': {e}")
        return None


# --- Core Business Logic ---
def evaluate_willdan_sizing(observed_hp: Optional[float], pc_existing_hp: Optional[float], observed_speed_pct: float) -> Tuple[str, bool, str]:
    """Evaluates sizing category and speed performance per Willdan QA/QC Manual."""
    if observed_hp is None or pc_existing_hp is None:
        return "Unknown", True, "Missing HP data for sizing evaluation."
    
    if observed_hp > pc_existing_hp:
        sizing_category = "Upsized"
        min_speed = 0.50
    elif observed_hp < pc_existing_hp:
        sizing_category = "Downsized"
        min_speed = 0.70
    else:
        sizing_category = "Equivalent-Sized"
        min_speed = 0.70
        
    speed_pass = observed_speed_pct >= min_speed
    status = "Pass" if speed_pass else "Fail"
    comment = (
        f"Sizing: {sizing_category} (Observed HP: {observed_hp} vs Baseline HP: {pc_existing_hp}). "
        f"Required Speed: >= {int(min_speed*100)}%, Observed: {observed_speed_pct*100:.1f}%. Result: {status}."
    )
    return sizing_category, speed_pass, comment


def process_motor_image(image_path: Path, session: requests.Session, pc_info: Dict, observed_speed: float) -> Optional[Dict[str, Any]]:
    """Executes the 3-tier extraction waterfall on a single motor image."""
    try:
        # Tier 1: Visual Extraction
        data = extract_motor_data(image_path, session)
        
        eff = normalize_efficiency(extract_number(data.get('Efficiency')))
        hp = extract_number(data.get('HP'))
        volts = extract_number(data.get('Voltage'))
        fla = extract_number(data.get('FLA'))
        phase = extract_number(data.get('Phase'))
        manufacturer = data.get('Manufacturer')
        spec_no = data.get('Spec_No')
        
        # Apply Willdan PF Standardization
        standard_pf = get_willdan_pf(hp)
        
        if eff:
            comment_source = f"Efficiency found on Nameplate. Willdan PF: {standard_pf} used."
        else:
            # Tier 2: Online Search
            raw_eff = search_efficiency_online(manufacturer, spec_no, session)
            eff = normalize_efficiency(raw_eff)
            if eff:
                comment_source = f"Efficiency found via Web Search ({manufacturer} {spec_no}). Willdan PF: {standard_pf} used."
            else:
                # Tier 3: Mathematical Calculation
                if all(v is not None for v in [hp, volts, fla, phase, standard_pf]):
                    logger.info(f"[{image_path.name}] Calculating efficiency via thermodynamic formula...")
                    numerator = hp * 746
                    denominator = volts * fla * math.sqrt(phase) * standard_pf
                    eff = round(numerator / denominator, 3) 
                    comment_source = f"Efficiency Calculated programmatically using Willdan PF {standard_pf}."
                else:
                    logger.warning(f"[{image_path.name}] Missing data constraints. Cannot calculate efficiency.")
                    comment_source = "Insufficient info to determine efficiency. Manual Review Required."
        
        # Sizing Evaluation
        pc_existing_hp = pc_info.get("PC_Existing_HP", hp)
        sizing_cat, speed_pass, sizing_comment = evaluate_willdan_sizing(hp, pc_existing_hp, observed_speed)
        
        logger.info(f"Processed {image_path.name} | Eff: {eff} | Sizing: {sizing_cat}")
        
        return {
            'Source_Image': image_path.name,
            'Motor ID': image_path.stem,
            'Manufacturer': manufacturer,
            'Spec/Cat No': spec_no,
            'HP Observed': hp,
            'PC Baseline HP': pc_existing_hp,
            'PC Proposed HP': pc_info.get("PC_Proposed_HP"),
            'Sizing Category': sizing_cat,
            'Observed Speed (%)': int(observed_speed * 100),
            'Nominal Efficiency Observed': eff,
            'PC Proposed Efficiency': pc_info.get("PC_Efficiency"),
            'Willdan Sizing Check': "Pass" if speed_pass else "Fail",
            'Inspection Comments': f"{comment_source} | {sizing_comment}"
        }
        
    except Exception as e:
        logger.error(f"Unexpected error processing {image_path.name}: {e}", exc_info=True)
        return None


def main() -> None:
    """Main execution pipeline."""
    if not IMAGE_DIR.exists():
        logger.error(f"Directory not found: {IMAGE_DIR}")
        return

    logger.info("Initializing OK3YO AI HVAC Automation Agent...")
    pc_data = load_pc_calculator_data(PC_TOOL_FILE)
    field_speeds = load_observed_speeds(SPEEDS_FILE)
    
    extracted_records = []
    
    # Using a session object dramatically improves API performance
    with requests.Session() as session:
        image_files = [f for f in IMAGE_DIR.iterdir() if f.suffix.lower() in {'.png', '.jpg', '.jpeg'}]
        
        if not image_files:
            logger.warning(f"No valid images found in {IMAGE_DIR}")
            return
            
        for image_path in image_files:
            motor_id = image_path.stem
            pc_info = pc_data.get(motor_id, {})
            observed_speed = field_speeds.get(motor_id, 0.70)
            
            record = process_motor_image(image_path, session, pc_info, observed_speed)
            if record:
                extracted_records.append(record)

    # DataFrame Export
    if extracted_records:
        df = pd.DataFrame(extracted_records)
        
        if OUTPUT_FILE.exists():
            existing_df = pd.read_excel(OUTPUT_FILE)
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df.to_excel(OUTPUT_FILE, index=False)
            logger.info(f"Workflow complete. Appended {len(df)} records to {OUTPUT_FILE.name}")
        else:
            df.to_excel(OUTPUT_FILE, index=False)
            logger.info(f"Workflow complete. Created {OUTPUT_FILE.name} with {len(df)} records.")
    else:
        logger.warning("No records were successfully extracted.")


if __name__ == "__main__":
    main()