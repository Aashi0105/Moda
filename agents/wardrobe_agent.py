"""Shop Inventory (Wardrobe) Agent module for Moda Multi-Agent Stylist (Phase 2).

Wraps the Shop Inventory Tool into a LangChain tool and exposes a dedicated Inventory Agent
powered by Gemini. Retrieves relevant available in-stock products from the shop's catalog.
"""

import os
import re
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from tools.wardrobe import get_wardrobe_items

# Load .env file explicitly from root directory
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=ENV_PATH)


@tool
def fetch_wardrobe_inventory(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    color: Optional[str] = None,
    formality: Optional[str] = None,
    season: Optional[str] = None,
    max_temp_c: Optional[float] = None,
    in_stock_only: bool = True
) -> list:
    """Queries the shop's inventory database to retrieve available in-stock clothing products.

    Args:
        category: Optional category filter ('top', 'bottom', 'outerwear', 'shoes', 'dress', 'accessory').
        subcategory: Optional subcategory filter (e.g., 'Shirt', 'Jeans', 'Sneakers', 'Blazer', etc.).
        color: Optional color filter (e.g., 'Blue', 'Black', 'White', 'Beige', etc.).
        formality: Optional formality level ('casual', 'smart casual', 'formal').
        season: Optional season filter ('Summer', 'Winter', 'Spring', 'Fall', 'All Season').
        max_temp_c: Optional current weather temperature in °C to filter comfortable items.
        in_stock_only: If True, only returns products where stock_quantity > 0. Defaults to True.
    """
    return get_wardrobe_items(
        category=category,
        subcategory=subcategory,
        color=color,
        formality=formality,
        season=season,
        max_temp_c=max_temp_c,
        in_stock_only=in_stock_only
    )


def create_wardrobe_llm() -> ChatGoogleGenerativeAI:
    """Initializes Gemini LLM bound with shop inventory query tools."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        abs_env = os.path.abspath(ENV_PATH)
        raise ValueError(
            f"No Gemini API key found in '.env'.\n"
            f"  -> Looked in: '{abs_env}'\n"
            f"  -> Please ensure '.env' has either GOOGLE_API_KEY=AIzaSy... or GEMINI_API_KEY=AIzaSy..."
        )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        temperature=0.0
    )
    return llm.bind_tools([fetch_wardrobe_inventory])


def _try_fast_inventory_lookup(query: str, max_temp_c: Optional[float] = None) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    """Fast-path deterministic query parser for shop inventory lookups.

    Answers standard inventory inquiries (e.g. 'show tops', 'formal clothing',
    'show inventory', 'what is in stock') by querying tools/wardrobe.py directly.
    Only retrieves items where stock_quantity > 0.
    """
    q = query.lower().strip()

    # Match category filter
    matched_category = None
    if "top" in q or "shirt" in q or "tee" in q or "sweater" in q:
        matched_category = "top"
    elif "bottom" in q or "pant" in q or "jean" in q or "trousers" in q or "short" in q:
        matched_category = "bottom"
    elif "outerwear" in q or "jacket" in q or "coat" in q or "windbreaker" in q or "blazer" in q:
        matched_category = "outerwear"
    elif "shoe" in q or "boot" in q or "sneaker" in q or "oxford" in q or "heel" in q or "loafer" in q:
        matched_category = "shoes"
    elif "dress" in q:
        matched_category = "dress"
    elif "accessory" in q or "scarf" in q or "sunglasses" in q or "bag" in q:
        matched_category = "accessory"

    # Match formality filter
    matched_formality = None
    if any(k in q for k in ["formal", "wedding", "black-tie", "gala"]):
        matched_formality = "formal"
    elif any(k in q for k in ["smart casual", "office", "meeting", "work", "interview", "party"]):
        matched_formality = "smart casual"
    elif any(k in q for k in ["casual", "weekend", "everyday", "relaxed", "outing"]) and "smart" not in q:
        matched_formality = "casual"

    # Match color filter
    matched_color = None
    for color_candidate in ["blue", "black", "white", "beige", "grey", "gray", "red", "navy", "charcoal", "khaki"]:
        if color_candidate in q:
            matched_color = color_candidate
            break

    # General inventory query match (closet/wardrobe compatibility + shop catalog terms + guided customer queries)
    is_general_query = any(phrase in q for phrase in [
        "what clothes do i have", "what clothes do i own", "show my wardrobe",
        "show all clothes", "list my clothes", "in my closet", "my closet",
        "shop inventory", "show inventory", "available inventory", "in stock",
        "available products", "store inventory", "browse inventory", "browse catalog",
        "show catalog", "what products do you have", "what clothes do you sell",
        "what is available to buy", "show available", "outfit", "complete outfit",
        "recommend", "wear", "wedding", "office", "meeting", "party", "everyday", "looking for",
        "birthday", "bday", "celebration", "date night", "brunch", "shopping", "something for"
    ])

    is_outfit_query = any(k in q for k in [
        "outfit", "complete outfit", "recommend", "wear", "shopping", "birthday",
        "bday", "brunch", "date night", "something for"
    ])

    if matched_category or matched_formality or matched_color or is_general_query:
        # For outfit queries without a specific single category, query all in-stock items
        # so the Stylist Agent's Suitability Guard has the full inventory context
        query_formality = None if (is_outfit_query and not matched_category) else matched_formality
        items = get_wardrobe_items(
            category=matched_category,
            formality=query_formality,
            color=matched_color,
            max_temp_c=max_temp_c,
            in_stock_only=True
        )
        if not items and max_temp_c is not None:
            # Fallback: retry without temperature constraint if temp filter returned 0 items
            items = get_wardrobe_items(
                category=matched_category,
                formality=matched_formality,
                color=matched_color,
                in_stock_only=True
            )

        if not items:
            summary = "No matching in-stock products found in the shop's inventory."
        else:
            item_lines = [
                f"- {item['name']} [{item.get('product_id', 'N/A')}] - ₹{item.get('price', 0):,.0f} "
                f"({item.get('color', '')} {item.get('subcategory') or item.get('category', '')}, "
                f"Sizes: {', '.join(item.get('available_sizes', [])) if isinstance(item.get('available_sizes'), list) else item.get('available_sizes')}, "
                f"In Stock: {item.get('stock_quantity', 0)})"
                for item in items
            ]
            summary = "Here are the matching available products in the shop's inventory:\n" + "\n".join(item_lines)
        return items, summary

    return None


def run_wardrobe_agent(query: str, weather_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """Runs the Inventory (Wardrobe) Agent to process a shop product inquiry.

    Args:
        query: Customer prompt (e.g., "Show formal clothing options", "What tops are in stock?").
        weather_data: Optional weather dict from Weather Agent (provides temperature for filtering).

    Returns:
        Dict containing:
            - agent_response: str (natural language summary of available shop products)
            - wardrobe_items: list of dicts (matching in-stock products from SQLite)
    """
    weather_data = weather_data or {}
    current_temp = weather_data.get("temperature")  # float or None
    if current_temp is not None:
        print(f"[WardrobeAgent] Received live weather: {current_temp}°C — filtering shop inventory by climate and in-stock availability")

    # 1. Fast-Path Optimization: Check for simple deterministic queries first
    fast_result = _try_fast_inventory_lookup(query, max_temp_c=current_temp)
    if fast_result is not None:
        items, summary = fast_result
        temp_str = f" (temp filter: {current_temp}°C)" if current_temp is not None else ""
        print(f"[WardrobeAgent FastPath] Resolved query directly via tools/wardrobe.py ({len(items)} in-stock items found){temp_str}")
        return {
            "agent_response": summary,
            "wardrobe_items": items
        }

    # 2. LLM Reasoning Path for complex or non-standard queries
    try:
        llm_with_tools = create_wardrobe_llm()

        prompt = (
            f"You are Moda's Shop Inventory Agent. Inspect the customer inquiry and invoke the 'fetch_wardrobe_inventory' tool "
            f"with appropriate category, subcategory, color, formality, season, or max_temp_c parameters if applicable.\n"
            f"Retrieve ONLY currently available products from the shop's inventory.\n"
            f"Customer Request: '{query}'"
        )

        ai_msg = llm_with_tools.invoke(prompt)

        items: List[Dict[str, Any]] = []
        tool_executed = False

        if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
            for tool_call in ai_msg.tool_calls:
                if tool_call["name"] == "fetch_wardrobe_inventory":
                    args = tool_call.get("args", {})
                    print(f"[WardrobeAgent] LLM triggered tool 'fetch_wardrobe_inventory' with args={args}")
                    items = get_wardrobe_items(
                        category=args.get("category"),
                        subcategory=args.get("subcategory"),
                        color=args.get("color"),
                        formality=args.get("formality"),
                        season=args.get("season"),
                        max_temp_c=args.get("max_temp_c"),
                        in_stock_only=args.get("in_stock_only", True)
                    )
                    tool_executed = True
                    break

        if not tool_executed:
            if weather_data:
                print("[WardrobeAgent Fallback] No specific tool call executed; providing climate-appropriate in-stock inventory.")
                items = get_wardrobe_items(max_temp_c=current_temp, in_stock_only=True)
            else:
                print("[WardrobeAgent Fallback] No specific tool call executed for query.")
                items = []

        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not items:
            summary_prompt = (
                f"Customer asked: '{query}'. Shop inventory returned 0 matching available products. "
                f"Provide an honest 1-sentence answer stating no such in-stock products currently exist in the shop's inventory."
            )
        else:
            summary_prompt = (
                f"Customer asked: '{query}'. Matching in-stock shop products: {items}.\n"
                f"Provide a clear bulleted list summarizing these available shop products with their product IDs, prices, and stock status."
            )

        final_response = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
            temperature=0.2
        ).invoke(summary_prompt)

        resp_text = final_response.content
        if isinstance(resp_text, list):
            resp_text = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in resp_text)
        elif not isinstance(resp_text, str):
            resp_text = str(resp_text)

        return {
            "agent_response": resp_text.strip(),
            "wardrobe_items": items
        }

    except Exception as e:
        # Graceful Rate Limit (429) & Exception Handling
        print(f"[WardrobeAgent Graceful Fallback] Gemini API unavailable/rate-limited: {e}")
        # Fall back to direct database retrieval of matching products
        q_lower = query.lower()
        all_in_stock = get_wardrobe_items(max_temp_c=current_temp, in_stock_only=True)
        q_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', q_lower))
        stop_words = {'what', 'have', 'show', 'tell', 'need', 'want', 'like', 'with', 'from', 'that', 'this', 'they', 'them', 'some', 'there', 'were', 'been', 'does', 'done', 'will', 'would', 'could', 'should', 'any', 'the'}
        meaningful_words = q_words - stop_words

        items = [
            it for it in all_in_stock
            if meaningful_words & (
                set(re.findall(r'\b[a-zA-Z]{3,}\b', it.get('name', '').lower())) |
                {it.get('category', '').lower()} |
                {str(it.get('subcategory', '')).lower()}
            )
        ]

        if not items and any(p in q_lower for p in ["all", "clothes", "wardrobe", "inventory", "stock", "catalog"]):
            items = all_in_stock

        if not items:
            fallback_msg = f"I checked our shop's inventory, and we do not have any products matching '{query}' in stock."
        else:
            item_list = ", ".join([f"{item['name']} ({item.get('product_id', 'N/A')})" for item in items[:5]])
            fallback_msg = (
                f"I checked the shop's current inventory directly: There are {len(items)} in-stock products available, "
                f"including {item_list}."
            )

        return {
            "agent_response": fallback_msg,
            "wardrobe_items": items
        }
