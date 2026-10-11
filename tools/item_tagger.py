"""Moda AI-Powered Clothing Photo-Tagging System.

Standalone inventory cataloging module that uses Gemini vision capabilities
to extract factual, structured clothing product tags from garment photographs.
The module enforces a strict fixed taxonomy and validates all responses independently
in Python to prevent hallucinations and maintain inventory data integrity.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

# Explicitly load .env from project root directory (matching Moda project convention)
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_PATH)

# Configure logger for rejection tracking
logger = logging.getLogger("item_tagger")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] item_tagger: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ==============================================================================
# TAXONOMY CONSTANTS
# ==============================================================================

ALLOWED_CATEGORIES: Set[str] = {
    "Top",
    "Bottom",
    "Outerwear",
    "Dress",
    "Shoes",
    "Accessory",
}

ALLOWED_SUBCATEGORIES: Dict[str, List[str]] = {
    "Top": [
        "T-shirt",
        "Shirt",
        "Blouse",
        "Tank Top",
        "Sweater",
        "Hoodie",
        "Polo",
        "Crop Top",
        "Kurti",
        "Other",
    ],
    "Bottom": [
        "Jeans",
        "Trousers",
        "Chinos",
        "Shorts",
        "Skirt",
        "Leggings",
        "Joggers",
        "Cargo Pants",
        "Other",
    ],
    "Outerwear": [
        "Jacket",
        "Blazer",
        "Coat",
        "Cardigan",
        "Shrug",
        "Vest",
        "Other",
    ],
    "Dress": [
        "Mini Dress",
        "Midi Dress",
        "Maxi Dress",
        "Shirt Dress",
        "Bodycon Dress",
        "A-line Dress",
        "Other",
    ],
    "Shoes": [
        "Sneakers",
        "Heels",
        "Flats",
        "Boots",
        "Sandals",
        "Loafers",
        "Other",
    ],
    "Accessory": [
        "Handbag",
        "Backpack",
        "Belt",
        "Scarf",
        "Hat",
        "Sunglasses",
        "Jewelry",
        "Watch",
        "Other",
    ],
}

ALLOWED_COLORS: Set[str] = {
    "Black",
    "White",
    "Grey",
    "Beige",
    "Brown",
    "Navy",
    "Blue",
    "Red",
    "Pink",
    "Purple",
    "Green",
    "Yellow",
    "Orange",
    "Cream",
    "Maroon",
    "Multicolor",
    "Other",
}

ALLOWED_PATTERNS: Set[str] = {
    "Solid",
    "Striped",
    "Checked",
    "Floral",
    "Polka Dot",
    "Graphic/Printed",
    "Geometric",
    "Other",
}

ALLOWED_FORMALITIES: Set[str] = {
    "Casual",
    "Smart Casual",
    "Formal",
}

ALLOWED_SEASONS: Set[str] = {
    "Summer",
    "Winter",
    "Monsoon/Rainy",
    "All Season",
}

ALLOWED_IMAGE_QUALITIES: Set[str] = {
    "Good",
    "Poor",
}

ALLOWED_IMAGE_EXTENSIONS: Set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

MIME_TYPE_MAP: Dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

DEFAULT_MODEL = os.getenv("GEMINI_TAGGER_MODEL", "gemini-3.5-flash")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3-flash-preview")


# ==============================================================================
# GEMINI CLIENT INITIALIZATION
# ==============================================================================

def get_gemini_client():
    """Initializes and returns the official Google GenAI client.
    
    Reuses existing project environment variable: GEMINI_API_KEY or GOOGLE_API_KEY.
    """
    try:
        from google import genai
    except ImportError:
        raise ImportError(
            "The 'google-genai' package is required. Please ensure google-genai is installed."
        )

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        abs_env = os.path.abspath(ENV_PATH)
        raise ValueError(
            f"No Gemini API key found in environment or '.env'.\n"
            f"  -> Looked in: '{abs_env}'\n"
            f"  -> Please set GEMINI_API_KEY or GOOGLE_API_KEY."
        )
    return genai.Client(api_key=api_key)


# ==============================================================================
# PROMPT DEFINITION
# ==============================================================================

def build_tagger_prompt() -> str:
    """Builds the strict, anti-hallucination classification prompt for Gemini."""
    
    # Format subcategory hierarchy for the prompt
    subcat_text = ""
    for cat, subcats in ALLOWED_SUBCATEGORIES.items():
        subcat_text += f"\n  - If Category is '{cat}':\n"
        for sc in subcats:
            subcat_text += f"      * {sc}\n"

    prompt = f"""You are Moda's precise clothing cataloging system.
Your sole task is factual visual classification of clothing items for inventory management.

CRITICAL ROLE BOUNDARIES:
- You are NOT acting as a stylist, fashion advisor, shopping assistant, product description writer, or creative model.
- You must perform factual visual classification only.
- Do NOT invent product names, marketing copy, descriptions, outfit combinations, or subjective fashion advice.
- Do NOT infer information that is not visually supported.
- Do NOT identify brand, price, material, size, or stock quantity unless visually explicit.

FIXED TAXONOMY & STRICT ALLOWED VALUES:
You must ONLY select values from these predefined allowed lists. Never create new values or free-text alternatives.

1. image_quality:
   Allowed values: "Good", "Poor"
   - "Good": Garment is sufficiently visible for reliable classification.
   - "Poor": Blurry, mostly hidden, too small, bad lighting, multiple garments make the target ambiguous, or not a clothing product.
   If "Poor", be conservative with other fields and return null where appropriate.

2. category:
   Allowed values: {json.dumps(sorted(list(ALLOWED_CATEGORIES)))}
   If the item cannot confidently be assigned to one of these categories, return null.

3. subcategory:
   The selected subcategory MUST belong to the selected category:
{subcat_text}
   - If category is 'Top', you MUST NOT return a Bottom, Dress, Shoes, or Accessory subcategory.
   - If the subcategory cannot be determined confidently, return null.

4. color:
   Allowed values: {json.dumps(sorted(list(ALLOWED_COLORS)))}
   Rules:
   - Select the single dominant visible color of the garment.
   - Do NOT describe shades using free text (e.g., never say "light blue", "sky blue", "off-white", "charcoal").
   - Map visually similar shades to the closest allowed value (e.g., sky blue -> Blue, charcoal -> Grey, ivory -> Cream).
   - If multiple clearly dominant colors exist across the garment, use "Multicolor".
   - If color cannot reasonably be determined, return null.

5. pattern:
   Allowed values: {json.dumps(sorted(list(ALLOWED_PATTERNS)))}
   Rules:
   - "Solid" means no clearly visible repeating or graphic pattern.
   - Use "Graphic/Printed" for logos, illustrations, text prints, or irregular graphic designs.
   - If pattern cannot confidently be determined, return null.

6. formality:
   Allowed values: ["Casual", "Smart Casual", "Formal"]
   Guidelines:
   - Casual: Everyday clothing (T-shirts, casual jeans, hoodies, joggers, casual sneakers).
   - Smart Casual: Polos, chinos, blouses, structured shirts, cardigans, loafers.
   - Formal: Blazers, formal trousers, formal dresses, formal shirts, suits, formal footwear.
   - Do not infer formality from brand, price, or subjective taste. If uncertain, return null.

7. season:
   Allowed values in array: ["Summer", "Winter", "Monsoon/Rainy", "All Season"]
   Rules:
   - Return an ARRAY because an item can belong to more than one season (e.g. ["Summer"], ["Winter", "All Season"]).
   - Lightweight breathable clothing -> Summer.
   - Heavy wool/fleece/thick clothing -> Winter.
   - Rainwear/water-resistant outerwear -> Monsoon/Rainy.
   - Versatile medium-weight clothing wearable year-round -> All Season.
   - Do not assign season simply because of garment color.
   - If season cannot reasonably be determined, return empty array [].

CONFIDENCE SCORES:
For every field, return "value" and "confidence" (number between 0.0 and 1.0).
- If uncertain, set "value": null and "confidence": 0.0 (for season: "value": [], "confidence": 0.0).
- Prefer: UNCERTAIN -> NULL over UNCERTAIN -> GUESS.

OUTPUT FORMAT REQUIREMENTS:
Return ONLY valid JSON.
No markdown fences (do not use ```json or ```).
No introductory or trailing text.
No comments, no explanations.

Strict JSON structure:
{{
  "image_quality": "Good",
  "category": {{
    "value": "Top",
    "confidence": 0.97
  }},
  "subcategory": {{
    "value": "Shirt",
    "confidence": 0.94
  }},
  "color": {{
    "value": "Blue",
    "confidence": 0.98
  }},
  "pattern": {{
    "value": "Striped",
    "confidence": 0.91
  }},
  "formality": {{
    "value": "Smart Casual",
    "confidence": 0.82
  }},
  "season": {{
    "value": ["Summer", "All Season"],
    "confidence": 0.78
  }}
}}"""
    return prompt


# ==============================================================================
# IMAGE HANDLING & VALIDATION
# ==============================================================================

def validate_image_file(image_path: str) -> Tuple[bool, Optional[str], Optional[bytes], Optional[str]]:
    """Validates that an image file exists, has a supported format, and is not corrupted.

    Args:
        image_path: Path to the image file.

    Returns:
        Tuple: (is_valid, error_message, image_bytes, mime_type)
    """
    path_obj = Path(image_path)
    if not path_obj.exists():
        return False, f"Image file not found: {image_path}", None, None

    if not path_obj.is_file():
        return False, f"Path is not a regular file: {image_path}", None, None

    ext = path_obj.suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return (
            False,
            f"Unsupported image extension '{ext}'. Supported formats: {sorted(list(ALLOWED_IMAGE_EXTENSIONS))}",
            None,
            None,
        )

    mime_type = MIME_TYPE_MAP.get(ext, "image/jpeg")

    # Verify image integrity using PIL
    try:
        with Image.open(image_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, Exception) as e:
        return False, f"Invalid or corrupted image file: {e}", None, None

    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
    except Exception as e:
        return False, f"Failed to read image bytes: {e}", None, None

    if len(image_bytes) == 0:
        return False, "Image file is empty (0 bytes).", None, None

    return True, None, image_bytes, mime_type


# ==============================================================================
# BACKEND INDEPENDENT VALIDATION LAYER
# ==============================================================================

def validate_field(
    image_name: str,
    field_name: str,
    field_payload: Any,
    allowed_values: Set[str],
    rejected_fields: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Validates a single classification field object {value, confidence} against allowed values."""
    if not isinstance(field_payload, dict):
        rejected_fields.append({
            "image_name": image_name,
            "field_name": field_name,
            "returned_value": field_payload,
            "reason": f"Field '{field_name}' must be an object with 'value' and 'confidence', got {type(field_payload).__name__}"
        })
        logger.warning(f"[{image_name}] Field '{field_name}' rejected: not an object ({field_payload})")
        return {"value": None, "confidence": 0.0}

    raw_val = field_payload.get("value")
    raw_conf = field_payload.get("confidence", 0.0)

    # Validate confidence
    try:
        conf = float(raw_conf)
        if not (0.0 <= conf <= 1.0):
            rejected_fields.append({
                "image_name": image_name,
                "field_name": f"{field_name}.confidence",
                "returned_value": raw_conf,
                "reason": f"Confidence must be between 0.0 and 1.0, got {conf}"
            })
            logger.warning(f"[{image_name}] Confidence out of bounds for '{field_name}': {conf}")
            conf = 0.0
    except (ValueError, TypeError):
        rejected_fields.append({
            "image_name": image_name,
            "field_name": f"{field_name}.confidence",
            "returned_value": raw_conf,
            "reason": f"Confidence must be numeric, got {type(raw_conf).__name__}"
        })
        logger.warning(f"[{image_name}] Non-numeric confidence for '{field_name}': {raw_conf}")
        conf = 0.0

    # If explicitly null, accept as null classification
    if raw_val is None:
        return {"value": None, "confidence": conf}

    # Validate string value against taxonomy
    if not isinstance(raw_val, str):
        rejected_fields.append({
            "image_name": image_name,
            "field_name": field_name,
            "returned_value": raw_val,
            "reason": f"Value must be a string or null, got {type(raw_val).__name__}"
        })
        logger.warning(f"[{image_name}] Field '{field_name}' rejected: value not a string ({raw_val})")
        return {"value": None, "confidence": 0.0}

    # Normalization check (case-sensitive check against exact taxonomy)
    if raw_val not in allowed_values:
        rejected_fields.append({
            "image_name": image_name,
            "field_name": field_name,
            "returned_value": raw_val,
            "reason": f"Value '{raw_val}' not in allowed {field_name} taxonomy: {sorted(list(allowed_values))}"
        })
        logger.warning(f"[{image_name}] Field '{field_name}' rejected: '{raw_val}' not in taxonomy")
        return {"value": None, "confidence": 0.0}

    return {"value": raw_val, "confidence": round(conf, 4)}


def validate_tags(
    raw_response_text: str,
    image_name: str
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]], str, Dict[str, int]]:
    """Performs strict independent Python validation of Gemini's output.

    Args:
        raw_response_text: Raw string output from Gemini.
        image_name: File basename for logging and rejection tracking.

    Returns:
        Tuple: (validated_tags, parsed_raw_json, rejected_fields, status, summary_counts)
    """
    rejected_fields: List[Dict[str, Any]] = []

    # 1. Clean markdown code fences if present
    cleaned_text = raw_response_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    elif cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    # 2. Parse JSON safely
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        rejected_fields.append({
            "image_name": image_name,
            "field_name": "json_root",
            "returned_value": raw_response_text[:200],
            "reason": f"JSON parsing failed: {e}"
        })
        logger.error(f"[{image_name}] JSON parsing failed: {e}")
        empty_tags = {
            "image_quality": "Poor",
            "category": {"value": None, "confidence": 0.0},
            "subcategory": {"value": None, "confidence": 0.0},
            "color": {"value": None, "confidence": 0.0},
            "pattern": {"value": None, "confidence": 0.0},
            "formality": {"value": None, "confidence": 0.0},
            "season": {"value": [], "confidence": 0.0}
        }
        summary = {
            "fields_attempted": 6,
            "fields_accepted": 0,
            "fields_returned_null": 0,
            "fields_rejected": 6
        }
        return empty_tags, None, rejected_fields, "FAILED", summary

    if not isinstance(data, dict):
        rejected_fields.append({
            "image_name": image_name,
            "field_name": "json_root",
            "returned_value": data,
            "reason": f"Expected JSON object, got {type(data).__name__}"
        })
        logger.error(f"[{image_name}] Expected JSON object root, got {type(data).__name__}")
        empty_tags = {
            "image_quality": "Poor",
            "category": {"value": None, "confidence": 0.0},
            "subcategory": {"value": None, "confidence": 0.0},
            "color": {"value": None, "confidence": 0.0},
            "pattern": {"value": None, "confidence": 0.0},
            "formality": {"value": None, "confidence": 0.0},
            "season": {"value": [], "confidence": 0.0}
        }
        summary = {
            "fields_attempted": 6,
            "fields_accepted": 0,
            "fields_returned_null": 0,
            "fields_rejected": 6
        }
        return empty_tags, data, rejected_fields, "FAILED", summary

    validated: Dict[str, Any] = {}

    # 3. Validate image_quality
    raw_quality = data.get("image_quality")
    if raw_quality in ALLOWED_IMAGE_QUALITIES:
        validated["image_quality"] = raw_quality
    else:
        rejected_fields.append({
            "image_name": image_name,
            "field_name": "image_quality",
            "returned_value": raw_quality,
            "reason": f"Value '{raw_quality}' not in allowed image qualities: {sorted(list(ALLOWED_IMAGE_QUALITIES))}"
        })
        logger.warning(f"[{image_name}] image_quality rejected: {raw_quality}")
        validated["image_quality"] = "Poor"

    # 4. Validate category
    validated["category"] = validate_field(
        image_name, "category", data.get("category"), ALLOWED_CATEGORIES, rejected_fields
    )

    # 5. Validate subcategory with category compatibility
    subcat_payload = data.get("subcategory")
    cat_val = validated["category"]["value"]

    if cat_val is None:
        # If Category is null, Subcategory must be null
        if isinstance(subcat_payload, dict) and subcat_payload.get("value") is not None:
            rejected_fields.append({
                "image_name": image_name,
                "field_name": "subcategory",
                "returned_value": subcat_payload.get("value"),
                "reason": "Subcategory was provided but Category is null. Incompatible hierarchy."
            })
            logger.warning(f"[{image_name}] Subcategory rejected: Category is null")
        validated["subcategory"] = {"value": None, "confidence": 0.0}
    else:
        allowed_subcats = set(ALLOWED_SUBCATEGORIES.get(cat_val, []))
        validated["subcategory"] = validate_field(
            image_name, "subcategory", subcat_payload, allowed_subcats, rejected_fields
        )

    # 6. Validate color
    validated["color"] = validate_field(
        image_name, "color", data.get("color"), ALLOWED_COLORS, rejected_fields
    )

    # 7. Validate pattern
    validated["pattern"] = validate_field(
        image_name, "pattern", data.get("pattern"), ALLOWED_PATTERNS, rejected_fields
    )

    # 8. Validate formality
    validated["formality"] = validate_field(
        image_name, "formality", data.get("formality"), ALLOWED_FORMALITIES, rejected_fields
    )

    # 9. Validate season (list of seasons)
    season_payload = data.get("season")
    if not isinstance(season_payload, dict):
        rejected_fields.append({
            "image_name": image_name,
            "field_name": "season",
            "returned_value": season_payload,
            "reason": f"Season field must be an object with 'value' and 'confidence', got {type(season_payload).__name__}"
        })
        logger.warning(f"[{image_name}] Season rejected: not an object ({season_payload})")
        validated["season"] = {"value": [], "confidence": 0.0}
    else:
        s_val = season_payload.get("value")
        s_conf_raw = season_payload.get("confidence", 0.0)
        try:
            s_conf = float(s_conf_raw)
            if not (0.0 <= s_conf <= 1.0):
                rejected_fields.append({
                    "image_name": image_name,
                    "field_name": "season.confidence",
                    "returned_value": s_conf_raw,
                    "reason": f"Season confidence must be between 0.0 and 1.0, got {s_conf}"
                })
                logger.warning(f"[{image_name}] Season confidence out of bounds: {s_conf}")
                s_conf = 0.0
        except (ValueError, TypeError):
            rejected_fields.append({
                "image_name": image_name,
                "field_name": "season.confidence",
                "returned_value": s_conf_raw,
                "reason": f"Season confidence must be numeric, got {type(s_conf_raw).__name__}"
            })
            logger.warning(f"[{image_name}] Non-numeric season confidence: {s_conf_raw}")
            s_conf = 0.0

        if not isinstance(s_val, list):
            rejected_fields.append({
                "image_name": image_name,
                "field_name": "season.value",
                "returned_value": s_val,
                "reason": f"Season value must be a list/array, got {type(s_val).__name__}"
            })
            logger.warning(f"[{image_name}] Season value not a list: {s_val}")
            validated["season"] = {"value": [], "confidence": 0.0}
        else:
            valid_seasons: List[str] = []
            for item in s_val:
                if item in ALLOWED_SEASONS:
                    if item not in valid_seasons:
                        valid_seasons.append(item)
                else:
                    rejected_fields.append({
                        "image_name": image_name,
                        "field_name": "season.value[]",
                        "returned_value": item,
                        "reason": f"Season item '{item}' not in allowed seasons: {sorted(list(ALLOWED_SEASONS))}"
                    })
                    logger.warning(f"[{image_name}] Season item rejected: '{item}' not in taxonomy")

            validated["season"] = {
                "value": valid_seasons,
                "confidence": round(s_conf, 4) if valid_seasons else 0.0
            }

    # 10. Compute Summary Counts and Overall Status
    classification_fields = ["category", "subcategory", "color", "pattern", "formality", "season"]
    fields_attempted = len(classification_fields)
    fields_accepted = 0
    fields_returned_null = 0

    # Collect set of rejected field names for statistics
    rejected_field_names = {
        rf["field_name"].split(".")[0] for rf in rejected_fields if rf["field_name"] != "image_quality"
    }
    fields_rejected = len(rejected_field_names)

    for fn in classification_fields:
        val = validated[fn]["value"]
        if fn == "season":
            is_present = len(val) > 0
        else:
            is_present = val is not None

        if is_present:
            fields_accepted += 1
        elif fn not in rejected_field_names:
            fields_returned_null += 1

    summary_counts = {
        "fields_attempted": fields_attempted,
        "fields_accepted": fields_accepted,
        "fields_returned_null": fields_returned_null,
        "fields_rejected": fields_rejected,
    }

    if validated["image_quality"] == "Poor" or fields_accepted == 0:
        status = "FAILED"
    elif fields_accepted == fields_attempted and fields_rejected == 0:
        status = "SUCCESS"
    else:
        status = "PARTIAL"

    return validated, data, rejected_fields, status, summary_counts


# ==============================================================================
# MAIN PUBLIC API FUNCTION
# ==============================================================================

def tag_clothing_item(
    image_path: str,
    model_name: Optional[str] = None
) -> Dict[str, Any]:
    """Exposes a clean, standalone function to tag clothing inventory items.

    Args:
        image_path: Path to the image file (JPG, PNG, WEBP).
        model_name: Optional Gemini model name override. Defaults to gemini-2.5-flash.

    Returns:
        Structured dictionary containing:
            - status: "SUCCESS" | "PARTIAL" | "FAILED"
            - image_path: str
            - image_name: str
            - image_quality: "Good" | "Poor"
            - raw_gemini_response: str
            - raw_parsed_response: Dict[str, Any] or None
            - validated_tags: Dict[str, Any]
            - rejected_fields: List[Dict[str, Any]]
            - summary: Dict[str, int]
            - model_used: str
            - error: Optional[str]
    """
    model_to_use = model_name or DEFAULT_MODEL
    image_name = Path(image_path).name

    # 1. Image validation
    is_valid, err_msg, image_bytes, mime_type = validate_image_file(image_path)
    if not is_valid:
        logger.error(f"[{image_name}] Image validation failed: {err_msg}")
        return {
            "status": "FAILED",
            "image_path": str(image_path),
            "image_name": image_name,
            "image_quality": "Poor",
            "raw_gemini_response": "",
            "raw_parsed_response": None,
            "validated_tags": {
                "image_quality": "Poor",
                "category": {"value": None, "confidence": 0.0},
                "subcategory": {"value": None, "confidence": 0.0},
                "color": {"value": None, "confidence": 0.0},
                "pattern": {"value": None, "confidence": 0.0},
                "formality": {"value": None, "confidence": 0.0},
                "season": {"value": [], "confidence": 0.0},
            },
            "rejected_fields": [{
                "image_name": image_name,
                "field_name": "image_file",
                "returned_value": image_path,
                "reason": err_msg
            }],
            "summary": {
                "fields_attempted": 6,
                "fields_accepted": 0,
                "fields_returned_null": 0,
                "fields_rejected": 6,
            },
            "model_used": model_to_use,
            "error": err_msg,
        }

    # 2. Initialize Gemini client
    try:
        client = get_gemini_client()
    except Exception as e:
        logger.error(f"[{image_name}] Gemini client initialization failed: {e}")
        return {
            "status": "FAILED",
            "image_path": str(image_path),
            "image_name": image_name,
            "image_quality": "Poor",
            "raw_gemini_response": "",
            "raw_parsed_response": None,
            "validated_tags": {
                "image_quality": "Poor",
                "category": {"value": None, "confidence": 0.0},
                "subcategory": {"value": None, "confidence": 0.0},
                "color": {"value": None, "confidence": 0.0},
                "pattern": {"value": None, "confidence": 0.0},
                "formality": {"value": None, "confidence": 0.0},
                "season": {"value": [], "confidence": 0.0},
            },
            "rejected_fields": [],
            "summary": {
                "fields_attempted": 6,
                "fields_accepted": 0,
                "fields_returned_null": 0,
                "fields_rejected": 6,
            },
            "model_used": model_to_use,
            "error": f"Gemini initialization error: {e}",
        }

    # 3. Call Gemini Vision API with automatic transient retry and model fallback
    from google.genai import types

    prompt = build_tagger_prompt()
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    candidate_models = [model_to_use]
    if FALLBACK_MODEL and FALLBACK_MODEL != model_to_use:
        candidate_models.append(FALLBACK_MODEL)

    raw_text = ""
    last_error = None
    actual_model_used = model_to_use

    for current_model in candidate_models:
        max_retries = 3
        initial_delay = 4.0
        success = False

        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=[image_part, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                raw_text = response.text or ""
                last_error = None
                actual_model_used = current_model
                success = True
                break
            except Exception as e:
                last_error = str(e)
                err_lower = last_error.lower()
                is_transient = (
                    "503" in last_error
                    or "429" in last_error
                    or "unavailable" in err_lower
                    or "resource_exhausted" in err_lower
                    or "quota" in err_lower
                )
                if is_transient and attempt < max_retries:
                    delay = initial_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[{image_name}] Transient Gemini API issue on {current_model}: {last_error[:80]}... "
                        f"Retrying in {delay:.1f}s (attempt {attempt}/{max_retries})..."
                    )
                    import time
                    time.sleep(delay)
                else:
                    logger.warning(f"[{image_name}] Model {current_model} failed on attempt {attempt}: {last_error[:100]}")
                    break

        if success:
            break
        elif len(candidate_models) > 1 and current_model != candidate_models[-1]:
            logger.warning(f"[{image_name}] Falling back from {current_model} to {candidate_models[-1]}...")

    if last_error and not raw_text:
        return {
            "status": "FAILED",
            "image_path": str(image_path),
            "image_name": image_name,
            "image_quality": "Poor",
            "raw_gemini_response": "",
            "raw_parsed_response": None,
            "validated_tags": {
                "image_quality": "Poor",
                "category": {"value": None, "confidence": 0.0},
                "subcategory": {"value": None, "confidence": 0.0},
                "color": {"value": None, "confidence": 0.0},
                "pattern": {"value": None, "confidence": 0.0},
                "formality": {"value": None, "confidence": 0.0},
                "season": {"value": [], "confidence": 0.0},
            },
            "rejected_fields": [{
                "image_name": image_name,
                "field_name": "api_call",
                "returned_value": None,
                "reason": f"Gemini API error: {last_error}"
            }],
            "summary": {
                "fields_attempted": 6,
                "fields_accepted": 0,
                "fields_returned_null": 0,
                "fields_rejected": 6,
            },
            "model_used": actual_model_used,
            "error": f"Gemini API error: {last_error}",
        }

    # 4. Strict Independent Python Validation
    validated_tags, parsed_raw, rejected_fields, status, summary = validate_tags(
        raw_text, image_name
    )

    return {
        "status": status,
        "image_path": str(image_path),
        "image_name": image_name,
        "image_quality": validated_tags.get("image_quality", "Good"),
        "raw_gemini_response": raw_text,
        "raw_parsed_response": parsed_raw,
        "validated_tags": validated_tags,
        "rejected_fields": rejected_fields,
        "summary": summary,
        "model_used": actual_model_used,
        "error": None if status != "FAILED" else (
            "Manual tagging required: image quality poor or classification failed."
        ),
    }
