"""Shop AI Stylist Agent module for Moda Multi-Agent Stylist (Phase 2 with Suitability Guard).

Consumes the outputs of the Weather Agent and Wardrobe (Inventory) Agent to synthesize
grounded, occasion-appropriate outfit recommendations from the shop's current available inventory.

Enforces:
1. Product Suitability Guard:
   - Understands occasion/formality requirements (e.g., Black-Tie -> Formal, Casual -> Casual).
   - Only recommends products appropriate for the request.
   - If suitable inventory does NOT exist, emits an Inventory Limitation Notice.
   - NEVER fills an outfit with unsuitable products (e.g., t-shirts/sneakers for a gala).
2. Strict Grounding & Anti-Hallucination:
   - Only recommends in-stock products supplied in the inventory context.
   - Out-of-stock items (stock_quantity = 0) are excluded.
"""

import os
import json
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# Explicitly load .env from project root directory
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_PATH)


def infer_requested_formality(prompt: str) -> Optional[str]:
    """Infers occasion formality requirement from the customer query."""
    p = prompt.lower()
    # Formal occasions: Black-tie, gala, tuxedo, ball, wedding, business formal, etc.
    if any(k in p for k in [
        "black-tie", "black tie", "gala", "tuxedo", "ball", "prom",
        "white tie", "wedding", "business formal", "formal", "formal event"
    ]):
        return "formal"

    # Smart casual occasions: meeting, office, interview, conference, business casual, party, birthday, date night
    if any(k in p for k in [
        "smart casual", "business casual", "meeting", "office", "work",
        "interview", "presentation", "conference", "client meeting",
        "party", "birthday", "bday", "celebration", "date night", "anniversary",
        "dinner date", "cocktail"
    ]):
        return "smart casual"

    # Casual occasions: outing, weekend, everyday, park, beach, casual, brunch
    if any(k in p for k in [
        "casual", "outing", "hangout", "weekend", "relaxed",
        "beach", "daily", "errands", "streetwear", "street", "park", "everyday", "brunch"
    ]):
        return "casual"

    return None


def infer_requested_item_type(prompt: str) -> str:
    """Infers if customer is looking specifically for a single item type instead of a complete outfit."""
    p = prompt.lower()

    if "outfit" in p or "complete" in p:
        return "outfit"

    if any(k in p for k in [
        "looking for top", "looking for: top", "item_type: top", "item type: top",
        "only top", "just top", "top only", "want a top", "need a top", "single top",
        "find a top", "recommend a top"
    ]) or p.strip().endswith("- top") or " - looking for top" in p or " - top " in p:
        return "top"

    if any(k in p for k in [
        "looking for bottom", "looking for: bottom", "item_type: bottom", "item type: bottom",
        "only bottom", "just bottom", "bottom only", "want a bottom", "need a bottom",
        "looking for pants", "only pants", "recommend bottoms", "recommend pants"
    ]) or p.strip().endswith("- bottom") or " - looking for bottom" in p or " - bottom " in p:
        return "bottom"

    if any(k in p for k in [
        "looking for dress", "looking for: dress", "item_type: dress", "item type: dress",
        "only dress", "just dress", "dress only", "want a dress", "need a dress",
        "recommend a dress"
    ]) or p.strip().endswith("- dress") or " - looking for dress" in p or " - dress " in p:
        return "dress"

    if any(k in p for k in [
        "looking for shoes", "looking for: shoes", "item_type: shoes", "item type: shoes",
        "only shoes", "just shoes", "shoes only", "want shoes", "need shoes",
        "recommend shoes", "footwear only"
    ]) or p.strip().endswith("- shoes") or " - looking for shoes" in p or " - shoes " in p:
        return "shoes"

    return "outfit"


def is_office_request(prompt: str) -> bool:
    """Checks whether the customer request is specifically for an office / work meeting context."""
    p = prompt.lower()
    return any(k in p for k in [
        "office", "meeting", "interview", "presentation", "conference",
        "corporate", "client meeting", "boardroom"
    ])


def is_product_suitable(product: Dict[str, Any], req_formality: Optional[str], is_office: bool = False) -> bool:
    """Checks whether an inventory product is appropriate for the requested formality and context."""
    if not req_formality and not is_office:
        return True

    name_lower = str(product.get("name", "")).lower()
    cat_lower = str(product.get("category", "")).lower().strip()
    subcat_lower = str(product.get("subcategory", "")).lower().strip()
    prod_formality = str(product.get("formality", "")).lower().strip().replace("_", " ")

    if is_office:
        # Exclude party-oriented pieces that are inappropriate for professional office meetings
        if cat_lower in ["dress", "one-piece", "bottom"] and ("mini" in name_lower.split() or "mini dress" in name_lower or subcat_lower in ["mini", "mini dress"]):
            return False
        if "stiletto" in name_lower or "stiletto" in subcat_lower:
            return False
        if "sunglasses" in name_lower or "sunglasses" in subcat_lower:
            return False
        if "shorts" in name_lower or "shorts" in subcat_lower:
            return False
        if "graphic" in name_lower:
            return False
        # Office tops and bottoms must be smart casual or formal
        if cat_lower in ["top", "bottom"]:
            return prod_formality in ["smart casual", "formal"]
        # Neat clean leather sneakers, loafers, flats, or formal shoes are suitable for smart casual office
        if cat_lower == "shoes":
            if prod_formality in ["smart casual", "formal"]:
                return True
            if prod_formality == "casual" and any(k in name_lower for k in ["sneaker", "loaf", "flat", "oxford"]):
                return True
            return False
        if cat_lower == "outerwear":
            return prod_formality in ["smart casual", "formal"]
        if cat_lower == "dress":
            return prod_formality in ["smart casual", "formal"]
        return False

    if req_formality == "formal":
        # Strict requirement: only genuinely formal products are appropriate.
        # Casual & Smart Casual products (e.g. t-shirt, jeans, chinos, casual shirts, sneakers) are UNSUITABLE.
        return prod_formality == "formal"

    if req_formality == "smart casual":
        # Smart casual accepts smart casual items and elevated formal pieces (e.g. blazer, dress trousers),
        # plus neat casual shoes/outerwear if appropriate.
        if prod_formality in ["smart casual", "formal"]:
            return True
        if cat_lower in ["shoes", "outerwear", "accessory"] and prod_formality == "casual":
            return True
        return False

    if req_formality == "casual":
        # Casual accepts casual and smart casual pieces, but excludes purely formal suit jackets/gowns
        # to avoid forcing formal blazers/trousers into casual outfits.
        return prod_formality in ["casual", "smart casual"]

    return True


def suitability_score(product: Dict[str, Any], req_formality: Optional[str], is_office: bool = False) -> int:
    """Ranks products by appropriateness for the requested formality (higher = better)."""
    if not req_formality and not is_office:
        return 10

    name_lower = str(product.get("name", "")).lower()
    cat_lower = str(product.get("category", "")).lower().strip()
    prod_formality = str(product.get("formality", "")).lower().strip().replace("_", " ")

    if is_office:
        if cat_lower == "top" and any(k in name_lower for k in ["oxford", "shirt", "blouse"]):
            return 15
        if cat_lower == "bottom" and any(k in name_lower for k in ["chino", "trouser", "dress trousers"]):
            return 15
        if cat_lower == "outerwear" and any(k in name_lower for k in ["suit", "blazer", "tailored"]):
            return 15
        if cat_lower == "shoes" and any(k in name_lower for k in ["oxford", "loafers", "minimalist white leather"]):
            return 14
        if prod_formality in ["smart casual", "formal"]:
            return 10
        return 0

    if prod_formality == req_formality:
        return 10  # Exact match

    if req_formality == "smart casual":
        if prod_formality == "formal":
            return 8   # Tasteful elevated alternative
        if prod_formality == "casual" and cat_lower in ["shoes", "outerwear", "accessory"]:
            return 6   # Clean casual footwear/accessory

    if req_formality == "casual":
        if prod_formality == "smart casual":
            return 7   # Smart casual is acceptable for casual, but casual is preferred

    return 0  # Unsuitable


def create_stylist_llm() -> ChatGoogleGenerativeAI:
    """Initializes and returns the Gemini LLM for reasoning."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        abs_env = os.path.abspath(ENV_PATH)
        raise ValueError(
            f"No Gemini API key found in '.env'.\n"
            f"  -> Looked in: '{abs_env}'\n"
            f"  -> Please ensure '.env' has either GOOGLE_API_KEY=AIzaSy... or GEMINI_API_KEY=AIzaSy..."
        )

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.2,
        timeout=15
    )


def calculate_total_price(items: List[Dict[str, Any]]) -> int:
    """Calculates bundle total price deterministically in Python from item prices."""
    total = 0
    for item in items:
        try:
            total += int(round(float(item.get("price", 0) or 0)))
        except (ValueError, TypeError):
            pass
    return total


def _sanitize_product_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitizes an inventory product dict for the customer outfit options schema."""
    raw_sizes = item.get("available_sizes")
    if isinstance(raw_sizes, list):
        sizes = raw_sizes
    elif isinstance(raw_sizes, str):
        try:
            sizes = json.loads(raw_sizes)
        except Exception:
            sizes = [s.strip() for s in raw_sizes.split(",") if s.strip()]
    else:
        sizes = []

    price_val = 0
    try:
        price_val = int(round(float(item.get("price", 0) or 0)))
    except (ValueError, TypeError):
        pass

    stock_val = 0
    try:
        stock_val = int(item.get("stock_quantity", 0) or 0)
    except (ValueError, TypeError):
        pass

    cat_raw = str(item.get("category", "")).strip()
    cat_cap = cat_raw.capitalize() if cat_raw else "Item"

    return {
        "id": item.get("id"),
        "product_id": item.get("product_id"),
        "name": item.get("name"),
        "category": cat_cap,
        "subcategory": item.get("subcategory"),
        "color": item.get("color"),
        "pattern": item.get("pattern"),
        "formality": item.get("formality"),
        "season": item.get("season"),
        "price": price_val,
        "sizes": sizes,
        "available_sizes": sizes,
        "stock": stock_val,
        "stock_quantity": stock_val,
        "image": item.get("image") or item.get("img") or "/uploads/default.jpg",
        "temp_min_c": item.get("temp_min_c"),
        "temp_max_c": item.get("temp_max_c")
    }


def generate_outfit_options(
    user_prompt: str,
    weather_data: Dict[str, Any],
    wardrobe_items: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], bool, str]:
    """Generates 1 to 3 distinct outfit options built exclusively from in-stock shop inventory.

    Returns:
        (outfit_options, is_inventory_notice, customer_message)
    """
    temp = float(weather_data.get('temperature', 26.0) or 26.0)
    rain_prob = int(weather_data.get('rain_probability', 0) or 0)
    city = weather_data.get('city', 'Vadodara')
    weather_desc = weather_data.get('weather', 'Clear')

    req_formality = infer_requested_formality(user_prompt)
    is_office = is_office_request(user_prompt)
    is_impossible = any(k in user_prompt.lower() for k in [
        "space suit", "spacesuit", "astronaut", "scuba", "wetsuit", "hazmat", "armor", "armour", "superhero"
    ])

    # 1. Filter strictly for in-stock products (stock_quantity > 0)
    available_pool = [i for i in wardrobe_items if int(i.get('stock_quantity', 1) or 0) > 0]

    # 2. Filter for suitable products based on occasion / formality / office context
    suitable_pool = [i for i in available_pool if is_product_suitable(i, req_formality, is_office=is_office)]

    # If no suitable products exist
    if not suitable_pool:
        if available_pool:
            msg = (
                f"We don't currently have enough suitable in-stock pieces for this request ('{user_prompt}'). "
                "The available products do not meet the requested occasion standards, and we do not substitute "
                "inappropriate casual products for formal requests. Please check back as our catalog is updated."
            )
        else:
            msg = (
                f"We don't currently have enough suitable in-stock pieces for this request ('{user_prompt}'). "
                "Please check back as new stock arrives or explore alternative categories."
            )
        return [], True, msg

    # Helper: Rank items by suitability score, temperature comfort, and weather appropriateness
    def _rank_items(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def _score(it):
            s_score = suitability_score(it, req_formality, is_office=is_office)
            temp_min = it.get('temp_min_c', -99) or -99
            temp_max = it.get('temp_max_c', 99) or 99
            temp_ok = 1 if (temp_min <= temp <= temp_max) else 0
            # Climate-controlled indoor office environment: suit jackets/blazers and button-down shirts are comfortable
            if is_office and str(it.get('category', '')).lower() in ['outerwear', 'top']:
                temp_ok = 1
            rain_pen = 0
            if rain_prob > 50 and str(it.get('subcategory', '')).lower() in ['sandals', 'sliders']:
                rain_pen = -2
            return (s_score, temp_ok + rain_pen)
        return sorted(candidates, key=_score, reverse=True)

    # -------------------------------------------------------------
    # Single Product Type Requests (Top, Bottom, Dress, Shoes)
    # -------------------------------------------------------------
    req_item_type = infer_requested_item_type(user_prompt)
    if req_item_type in ["top", "bottom", "dress", "shoes"]:
        target_candidates = _rank_items([
            i for i in suitable_pool
            if str(i.get('category', '')).lower() == req_item_type.lower()
        ])
        cat_title = req_item_type.capitalize()
        if not target_candidates:
            formality_label = f"a {req_formality}" if req_formality else "this"
            msg = (
                f"We don't currently have enough suitable in-stock pieces for this request ('{user_prompt}'). "
                f"Our catalog does not currently have an in-stock {cat_title.lower()} suitable for {formality_label} occasion."
            )
            return [], True, msg

        options = []
        for item in target_candidates[:3]:
            sanitized = _sanitize_product_item(item)
            title = f"{item['name']}"
            vibe = f"Curated {cat_title} for {user_prompt.title()}"
            rationale = (
                f"Selected from our boutique inventory tailored for '{user_prompt}' in {city} "
                f"({temp}°C, {weather_desc}). Verified in stock and occasion-appropriate."
            )
            options.append({
                "title": title,
                "vibe": vibe,
                "items": [sanitized],
                "total_price": sanitized["price"],
                "rationale": rationale,
                "formula": f"single_{req_item_type}"
            })
        return options, False, ""

    # -------------------------------------------------------------
    # Complete Outfit Requests
    # -------------------------------------------------------------
    dresses = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'dress'])
    tops = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'top'])
    bottoms = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'bottom'])
    outerwear = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'outerwear'])
    shoes = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'shoes'])
    accessories = _rank_items([i for i in suitable_pool if str(i.get('category', '')).lower() == 'accessory'])

    # Ethnic items
    ethnic_tops = [t for t in tops if any(k in (t.get('name', '') + ' ' + str(t.get('subcategory', ''))).lower() for k in ['kurti', 'kurta', 'ethnic', 'sherwani'])]
    ethnic_shoes = [s for s in shoes if any(k in (s.get('name', '') + ' ' + str(s.get('subcategory', ''))).lower() for k in ['jutti', 'juttis', 'kolhapuri', 'mojari'])]

    options = []
    used_product_ids = set()

    if is_office:
        # -------------------------------------------------------------
        # OFFICE SUITABILITY PATH: Prioritize professional separates & layered tailoring
        # Excludes party mini dresses, high stilettos, and sunglasses.
        # -------------------------------------------------------------
        # FORMULA 2 (Office Look 1): Classic Separates (Top + Bottom + Footwear)
        if tops and bottoms and shoes:
            t1 = tops[0]
            b1 = bottoms[0]
            s1 = shoes[0]
            look_items = [t1, b1, s1]
            sanitized_items = [_sanitize_product_item(it) for it in look_items]
            bundle_price = calculate_total_price(sanitized_items)
            options.append({
                "title": "Executive Polish",
                "vibe": "Refined & Professional",
                "items": sanitized_items,
                "total_price": bundle_price,
                "rationale": f"Crisp {t1['name']} paired with structured {b1['name']} and {s1['name']} delivers a clean, professional presence for office meetings.",
                "formula": "classic_separates"
            })
            for it in look_items:
                used_product_ids.add(it.get('product_id'))

        # FORMULA 3 (Office Look 2): Layered Statement (Top + Bottom + Outerwear/Suit Jacket + Footwear)
        if outerwear and tops and bottoms and shoes:
            formal_outer = [o for o in outerwear if any(k in str(o.get('name', '') + ' ' + str(o.get('subcategory', ''))).lower() for k in ['suit', 'blazer', 'tailored'])]
            o1 = formal_outer[0] if formal_outer else outerwear[0]

            avail_tops = [t for t in tops if t.get('product_id') not in used_product_ids]
            t2 = avail_tops[0] if avail_tops else tops[0]

            avail_bottoms = [b for b in bottoms if b.get('product_id') not in used_product_ids]
            b2 = avail_bottoms[0] if avail_bottoms else bottoms[0]

            avail_shoes = [s for s in shoes if s.get('product_id') not in used_product_ids]
            s2 = avail_shoes[0] if avail_shoes else shoes[0]

            look_items = [t2, b2, o1, s2]
            sanitized_items = [_sanitize_product_item(it) for it in look_items]
            bundle_price = calculate_total_price(sanitized_items)
            options.append({
                "title": "Tailored Authority",
                "vibe": "Structured & Sophisticated",
                "items": sanitized_items,
                "total_price": bundle_price,
                "rationale": f"Structured {o1['name']} layered over {t2['name']} with {b2['name']} and {s2['name']} offers boardroom-level sophistication.",
                "formula": "layered_statement"
            })

        # FORMULA 1 (Office Look 3, if genuinely suitable office dress exists):
        if len(options) < 3 and dresses and shoes:
            office_dresses = [d for d in dresses if "mini" not in str(d.get('name', '')).lower() and "mini" not in str(d.get('subcategory', '')).lower()]
            if office_dresses:
                d1 = office_dresses[0]
                s3 = shoes[0]
                look_items = [d1, s3]
                sanitized_items = [_sanitize_product_item(it) for it in look_items]
                bundle_price = calculate_total_price(sanitized_items)
                options.append({
                    "title": "Smart Tailored Dress",
                    "vibe": "Poised & Professional",
                    "items": sanitized_items,
                    "total_price": bundle_price,
                    "rationale": f"Professional silhouette featuring {d1['name']} paired with {s3['name']}.",
                    "formula": "one_piece"
                })

    else:
        # -------------------------------------------------------------
        # STANDARD OCCASION PATH (Birthday, Casual, Party, etc.)
        # -------------------------------------------------------------
        # FORMULA 1: One-Piece Look (Dress + Footwear + optional Accessory)
        if dresses and shoes:
            d = dresses[0]
            dress_shoes = [s for s in shoes if str(s.get('subcategory', '')).lower() in ['heels', 'sandals', 'flats']]
            s1 = dress_shoes[0] if dress_shoes else shoes[0]

            look_items = [d, s1]
            if accessories:
                look_items.append(accessories[0])

            sanitized_items = [_sanitize_product_item(it) for it in look_items]
            bundle_price = calculate_total_price(sanitized_items)

            acc_name = f" and {accessories[0]['name']}" if accessories else ""
            rationale = (
                f"An effortless one-piece look centering our {d['name']} paired with {s1['name']}{acc_name}. "
                f"Tailored for {city}'s {temp}°C weather ({weather_desc}). Verified in stock."
            )

            title = "Effortless Glam" if req_formality in ["smart casual", "formal"] else "Breezy One-Piece"
            vibe = "Elegant and party-ready" if req_formality in ["smart casual", "formal"] else "Relaxed, feminine silhouette"

            options.append({
                "title": title,
                "vibe": vibe,
                "items": sanitized_items,
                "total_price": bundle_price,
                "rationale": rationale,
                "formula": "one_piece"
            })
            for it in look_items:
                used_product_ids.add(it.get('product_id'))

        # FORMULA 2: Classic Separates (Top + Bottom + Footwear + optional Accessory)
        if tops and bottoms and shoes:
            t1 = tops[0]
            b1 = bottoms[0]
            shoes_candidates = [s for s in shoes if s.get('product_id') not in used_product_ids]
            s2 = shoes_candidates[0] if shoes_candidates else shoes[0]

            look_items = [t1, b1, s2]
            acc_candidates = [a for a in accessories if a.get('product_id') not in used_product_ids]
            if acc_candidates and len(look_items) < 4:
                look_items.append(acc_candidates[0])

            sanitized_items = [_sanitize_product_item(it) for it in look_items]
            bundle_price = calculate_total_price(sanitized_items)

            title = "Chic Duo" if req_formality == "smart casual" else ("Relaxed Separates" if req_formality == "casual" else "Tailored Elegance")
            vibe = "Refined and versatile pairing" if req_formality == "smart casual" else "Comfortable, contemporary everyday aesthetic"
            rationale = (
                f"Pairs our {t1['name']} with {b1['name']} and {s2['name']}. "
                f"A versatile combination suited for {temp}°C in {city}. Verified in stock."
            )

            options.append({
                "title": title,
                "vibe": vibe,
                "items": sanitized_items,
                "total_price": bundle_price,
                "rationale": rationale,
                "formula": "classic_separates"
            })
            for it in look_items:
                used_product_ids.add(it.get('product_id'))

        # FORMULA 3: Layered / Statement Look (Top + Bottom + Outerwear + Footwear)
        if outerwear and tops and bottoms and shoes:
            o_candidates = [o for o in outerwear if (o.get('temp_min_c', -99) <= temp <= o.get('temp_max_c', 99))]
            if not o_candidates:
                if temp < 18.0:
                    o_candidates = [o for o in outerwear if str(o.get('subcategory', '')).lower() in ['coat', 'jacket']] or outerwear
                elif rain_prob > 50:
                    o_candidates = [o for o in outerwear if 'windbreaker' in str(o.get('name', '')).lower()] or outerwear
                elif req_formality in ["formal", "smart casual"]:
                    o_candidates = [o for o in outerwear if any(k in str(o.get('name', '') + ' ' + str(o.get('subcategory', ''))).lower() for k in ['suit', 'blazer', 'tailored'])] or outerwear
                else:
                    o_candidates = [o for o in outerwear if 'windbreaker' in str(o.get('name', '')).lower()] or outerwear

            if o_candidates:
                o1 = o_candidates[0]
                avail_tops = [t for t in tops if t.get('product_id') not in used_product_ids]
                t2 = avail_tops[0] if avail_tops else (tops[-1] if len(tops) > 1 else tops[0])

                avail_bottoms = [b for b in bottoms if b.get('product_id') not in used_product_ids]
                b2 = avail_bottoms[0] if avail_bottoms else (bottoms[-1] if len(bottoms) > 1 else bottoms[0])

                avail_shoes = [s for s in shoes if s.get('product_id') not in used_product_ids]
                s3 = avail_shoes[0] if avail_shoes else (shoes[-1] if len(shoes) > 1 else shoes[0])

                look_items = [t2, b2, o1, s3]
                sanitized_items = [_sanitize_product_item(it) for it in look_items]
                bundle_price = calculate_total_price(sanitized_items)

                title = "Statement" if req_formality in ["smart casual", "formal"] else "Layered Utility"
                vibe = "Elevated presence with layered depth" if req_formality in ["smart casual", "formal"] else "Weather-ready layered styling"
                rationale = (
                    f"Elevates {t2['name']} and {b2['name']} with our {o1['name']}, finished with {s3['name']}. "
                    f"Offers optimal layering for {city} conditions ({temp}°C, {weather_desc}). Verified in stock."
                )

                options.append({
                    "title": title,
                    "vibe": vibe,
                    "items": sanitized_items,
                    "total_price": bundle_price,
                    "rationale": rationale,
                    "formula": "layered_statement"
                })

        # FORMULA 4: Ethnic / Fusion Look (only if genuine ethnic items are present)
        if len(options) < 3 and ethnic_tops and bottoms and (ethnic_shoes or shoes):
            et = ethnic_tops[0]
            eb = bottoms[0]
            es = ethnic_shoes[0] if ethnic_shoes else shoes[0]
            look_items = [et, eb, es]
            sanitized_items = [_sanitize_product_item(it) for it in look_items]
            bundle_price = calculate_total_price(sanitized_items)
            options.append({
                "title": "Ethnic Fusion",
                "vibe": "Traditional elegance with modern comfort",
                "items": sanitized_items,
                "total_price": bundle_price,
                "rationale": f"Celebrates festive styling with {et['name']} paired with {eb['name']} and {es['name']}.",
                "formula": "ethnic_fusion"
            })

    # Impossible item inquiry handling (e.g. spacesuit)
    if is_impossible:
        impossible_term = "space suits" if any(k in user_prompt.lower() for k in ["space suit", "spacesuit", "astronaut"]) else "specialized costume attire"
        notice_msg = (
            f"Moda does not carry {impossible_term} in our current boutique inventory. "
            f"However, here are our closest in-stock party looks curated from our real collection for your event:"
        )
        return options[:3], True, notice_msg

    # Inventory limitation and partial inventory handling (strictly avoid fabricating)
    if not options:
        # Check for partial inventory (e.g. only tops or only bottoms available)
        top_prod = tops[0] if tops else None
        bottom_prod = bottoms[0] if bottoms else None
        dress_prod = dresses[0] if dresses else None

        if top_prod is not None or bottom_prod is not None or dress_prod is not None:
            avail_parts = []
            missing_parts = []
            if top_prod:
                avail_parts.append("top")
            else:
                missing_parts.append("top")
            if bottom_prod:
                avail_parts.append("bottom")
            else:
                missing_parts.append("bottom")

            partial_item = top_prod or bottom_prod or dress_prod
            sanitized = _sanitize_product_item(partial_item)
            partial_msg = (
                f"We found a suitable in-stock {' and '.join(avail_parts)} for '{user_prompt}', "
                f"but currently lack suitable in-stock pieces for {' and '.join(missing_parts)} "
                "to compose a complete outfit. We do not substitute inappropriate or out-of-stock items."
            )
            options.append({
                "title": f"Partial Look ({partial_item['name']})",
                "vibe": "Limited shop inventory for complete look",
                "items": [sanitized],
                "total_price": sanitized["price"],
                "rationale": partial_msg,
                "formula": "partial_inventory",
                "is_partial": True
            })
            return options, True, partial_msg

        formality_label = f"a {req_formality}" if req_formality else "this"
        msg = (
            f"We don't currently have enough suitable in-stock pieces for this request ('{user_prompt}'). "
            f"Our catalog does not have sufficient in-stock items suitable for {formality_label} occasion."
        )
        return [], True, msg

    is_notice = len(options) < 3
    if is_notice:
        notice_msg = (
            f"We currently have {len(options)} distinct look{'s' if len(options) != 1 else ''} that match your request. "
            "Our boutique currently has limited suitable inventory for this occasion."
        )
    else:
        notice_msg = ""

    return options[:3], is_notice, notice_msg


def _format_markdown_recommendations(
    options: List[Dict[str, Any]],
    user_prompt: str,
    weather_data: Dict[str, Any],
    is_notice: bool,
    notice_msg: str
) -> str:
    """Formats options into structured Markdown string for backwards compatibility."""
    if not options:
        return f"### ⚠️ Inventory Notice\n{notice_msg}"

    # Handle partial inventory output for backwards compatibility
    if options and options[0].get("is_partial"):
        opt = options[0]
        it = opt["items"][0]
        cat_lower = it["category"].lower()
        sizes_str = ", ".join(it['sizes']) if isinstance(it.get('sizes'), list) else str(it.get('sizes', ''))
        sizes_part = f" | Sizes: {sizes_str}" if sizes_str else ""
        item_line = f"{it['name']} ({it.get('product_id', 'N/A')}) - ₹{it['price']:,}{sizes_part} | In Stock: {it.get('stock', 0)}"

        top_line = item_line if cat_lower == "top" else "None available in current inventory"
        bottom_line = item_line if cat_lower == "bottom" else "None available in current inventory"

        return (
            "### 👔 Partial Outfit (Limited Inventory)\n"
            f"- **Top:** {top_line}\n"
            f"- **Bottom:** {bottom_line}\n"
            "- **Outerwear:** None available in current inventory\n"
            "- **Shoes:** None available in current inventory\n\n"
            f"### ⚠️ Inventory Notice\n"
            f"{notice_msg}"
        )

    lines = []
    # If limited inventory notice applies alongside partial options
    if is_notice and notice_msg:
        lines.append(f"### ⚠️ Inventory Notice\n{notice_msg}\n")

    lines.append(f"### 👔 Recommended Outfits ({len(options)} Distinct Looks)\n")

    for idx, opt in enumerate(options, 1):
        lines.append(f"#### Look {idx}: {opt['title']} (₹{opt['total_price']:,}) — {opt['vibe']}")
        for it in opt["items"]:
            sizes_str = ", ".join(it['sizes']) if isinstance(it.get('sizes'), list) else str(it.get('sizes', ''))
            sizes_part = f" | Sizes: {sizes_str}" if sizes_str else ""
            lines.append(f"- **{it['category']}:** {it['name']} ({it.get('product_id', 'N/A')}) - ₹{it['price']:,}{sizes_part} | In Stock: {it.get('stock', 0)}")
        lines.append(f"\n*Stylist Rationale:* {opt['rationale']}\n")

    # Add legacy single-look block from Look 1 for existing parser backwards compatibility
    opt1 = options[0]
    lines.append("### 👔 Recommended Outfit")
    for it in opt1["items"]:
        sizes_str = ", ".join(it['sizes']) if isinstance(it.get('sizes'), list) else str(it.get('sizes', ''))
        sizes_part = f" | Sizes: {sizes_str}" if sizes_str else ""
        lines.append(f"- **{it['category']}:** {it['name']} ({it.get('product_id', 'N/A')}) - ₹{it['price']:,}{sizes_part} | In Stock: {it.get('stock', 0)}")

    lines.append("\n### 💡 Stylist Rationale")
    lines.append(opt1["rationale"])

    return "\n".join(lines)


def run_stylist_agent(
    user_prompt: str,
    weather_data: Dict[str, Any],
    wardrobe_items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Runs the Stylist Agent to synthesize distinct, grounded outfit options from available shop inventory.

    Args:
        user_prompt: The customer's styling query or intent.
        weather_data: Structured weather dictionary from Weather Agent.
        wardrobe_items: List of clothing product dictionaries from Wardrobe/Inventory Agent.

    Returns:
        Dict containing:
            - agent_response: str (structured Markdown outfit recommendation or inventory limitation notice)
            - outfit_options: List[Dict[str, Any]] (1 to 3 structured distinct outfit options)
            - inventory_notice: bool
            - customer_message: str
    """
    options, is_notice, notice_msg = generate_outfit_options(user_prompt, weather_data, wardrobe_items)
    markdown_resp = _format_markdown_recommendations(options, user_prompt, weather_data, is_notice, notice_msg)

    return {
        "agent_response": markdown_resp,
        "outfit_options": options,
        "inventory_notice": is_notice,
        "customer_message": notice_msg
    }
