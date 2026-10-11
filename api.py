"""Python HTTP API Backend for Moda Multi-Agent Stylist.

Exposes a REST API endpoint 'POST /recommend' that invokes the LangGraph Supervisor graph
and returns structured JSON recommendations to the Node.js / Express website server.
"""

import os
import sys
import re
import json
import time
from typing import List, Dict, Any, Optional, Union
from http.server import HTTPServer, BaseHTTPRequestHandler

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def _load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("'\"")

_load_env_file()
sys.path.append(os.path.dirname(__file__))


from graph import app_graph, AgentState


def parse_outfit_from_text(text: str, wardrobe_items: List[dict] = None) -> dict:
    """Parses structured outfit recommendations and matches item names to wardrobe database objects with IDs."""
    if wardrobe_items is None:
        wardrobe_items = []

    def _find_item(cat: str, raw_name: Optional[str]) -> Optional[dict]:
        if not raw_name:
            return None
        clean_name = re.sub(r'[\*_`]+', '', raw_name).strip()
        clean = clean_name.lower()
        if not clean or clean.startswith("none") or clean in ("n/a", "none needed", "none.", "none available in current inventory"):
            return None

        # 1. Search wardrobe_items (from state) for matching name or product_id
        for item in wardrobe_items:
            cat_val = str(item.get("category", "")).lower()
            p_id = str(item.get("product_id", "")).lower()
            name = str(item.get("name", "")).lower()
            if cat.lower() in cat_val or cat_val in cat.lower() or cat in ("top", "bottom", "dress", "shoes", "outerwear"):
                if (p_id and p_id in clean) or (name and (name in clean or clean in name)):
                    return {
                        "id": item.get("id"),
                        "product_id": item.get("product_id"),
                        "name": item.get("name"),
                        "image": item.get("image") or item.get("img"),
                        "category": item.get("category"),
                        "subcategory": item.get("subcategory"),
                        "color": item.get("color"),
                        "pattern": item.get("pattern"),
                        "formality": item.get("formality"),
                        "season": item.get("season"),
                        "price": item.get("price"),
                        "available_sizes": item.get("available_sizes"),
                        "stock_quantity": item.get("stock_quantity")
                    }

        # 2. Fallback: Search the full SQLite wardrobe database (wardrobe.db) directly
        try:
            from tools.wardrobe import get_wardrobe_items
            db_items = get_wardrobe_items(category=cat, in_stock_only=False) or get_wardrobe_items(in_stock_only=False)
            for item in db_items:
                p_id = str(item.get("product_id", "")).lower()
                name = str(item.get("name", "")).lower()
                if (p_id and p_id in clean) or (name and (name in clean or clean in name)):
                    return {
                        "id": item.get("id"),
                        "product_id": item.get("product_id"),
                        "name": item.get("name"),
                        "image": item.get("image") or item.get("img"),
                        "category": item.get("category"),
                        "subcategory": item.get("subcategory"),
                        "color": item.get("color"),
                        "pattern": item.get("pattern"),
                        "formality": item.get("formality"),
                        "season": item.get("season"),
                        "price": item.get("price"),
                        "available_sizes": item.get("available_sizes"),
                        "stock_quantity": item.get("stock_quantity")
                    }
        except Exception:
            pass

        return {
            "id": None,
            "product_id": None,
            "name": clean_name,
            "image": None,
            "price": None,
            "available_sizes": [],
            "stock_quantity": 0
        }

    # Detect if response is an inventory limitation notice
    is_notice = ("inventory notice" in text.lower() or
                 "does not contain enough suitable" in text.lower() or
                 "we don't currently have enough suitable" in text.lower() or
                 "lacks suitable" in text.lower())
    is_partial = "partial outfit" in text.lower()

    if is_notice and not is_partial and not any(k in text.lower() for k in ["recommended top", "recommended bottom", "recommended dress", "recommended shoes", "recommended outfit"]):
        return {
            "top": None,
            "bottom": None,
            "dress": None,
            "outerwear": None,
            "shoes": None,
            "accessories": None,
            "inventory_notice": True,
            "partial_inventory": False,
            "customer_message": "We don't currently have enough suitable in-stock pieces for this request. Please check back as our catalog is updated or explore alternative categories."
        }

    raw_parsed = {
        "top": None,
        "bottom": None,
        "dress": None,
        "outerwear": None,
        "shoes": None,
        "accessories": None
    }

    lines = text.split("\n")
    for line in lines:
        l = line.strip().lower()
        cleaned_line = re.sub(r'[\*_`]+', '', line).strip()
        cl_lower = cleaned_line.lower()

        if "top:" in l or "top:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["top"] = re.sub(r'[\*_`]+', '', val).strip()
        elif "bottom:" in l or "bottom:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["bottom"] = re.sub(r'[\*_`]+', '', val).strip()
        elif "dress:" in l or "dress:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["dress"] = re.sub(r'[\*_`]+', '', val).strip()
        elif "outerwear:" in l or "outerwear:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["outerwear"] = re.sub(r'[\*_`]+', '', val).strip()
        elif "shoes:" in l or "shoes:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["shoes"] = re.sub(r'[\*_`]+', '', val).strip()
        elif "accessories:" in l or "accessory:" in l or "accessories:" in cl_lower or "accessory:" in cl_lower:
            val = line.split(":", 1)[-1] if ":" in line else cleaned_line.split(":", 1)[-1]
            raw_parsed["accessories"] = re.sub(r'[\*_`]+', '', val).strip()

    parsed_top = _find_item("top", raw_parsed["top"])
    parsed_bottom = _find_item("bottom", raw_parsed["bottom"])
    parsed_dress = _find_item("dress", raw_parsed["dress"])
    parsed_outerwear = _find_item("outerwear", raw_parsed["outerwear"])
    parsed_shoes = _find_item("shoes", raw_parsed["shoes"])
    cleaned_accessories = re.sub(r'[\*_`]+', '', raw_parsed["accessories"]).strip() if raw_parsed["accessories"] else None

    # If all items are None and notice is present
    if is_notice and not any([parsed_top, parsed_bottom, parsed_dress, parsed_shoes]):
        return {
            "top": None,
            "bottom": None,
            "dress": None,
            "outerwear": None,
            "shoes": None,
            "accessories": None,
            "inventory_notice": True,
            "partial_inventory": False,
            "customer_message": "We don't currently have enough suitable in-stock pieces for this request. Please check back as our catalog is updated or explore alternative categories."
        }

    return {
        "top": parsed_top,
        "bottom": parsed_bottom,
        "dress": parsed_dress,
        "outerwear": parsed_outerwear,
        "shoes": parsed_shoes,
        "accessories": cleaned_accessories,
        "inventory_notice": is_notice,
        "partial_inventory": is_partial,
        "customer_message": "Some components are not currently available in-stock." if is_partial else ""
    }



class LangGraphAPIHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler exposing POST /recommend and POST /api/recommend."""

    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Health check, info, staff HTML, and staff catalog endpoints."""
        clean_path = self.path.split("?")[0]
        
        # Serve staff review page
        if clean_path in ["/staff", "/staff.html"]:
            staff_html_path = os.path.join(os.path.dirname(__file__), "staff.html")
            if os.path.exists(staff_html_path):
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(staff_html_path, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        # Staff taxonomy options endpoint
        if clean_path in ["/api/staff/taxonomy", "/staff/taxonomy"]:
            from services.staff_catalog import get_taxonomy_options
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            opts = get_taxonomy_options()
            self.wfile.write(json.dumps({"success": True, "taxonomy": opts}, indent=2).encode("utf-8"))
            return

        # Staff products list endpoint
        if clean_path in ["/api/staff/products", "/staff/products"]:
            from tools.wardrobe import get_wardrobe_items
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            all_prods = get_wardrobe_items(in_stock_only=False)
            self.wfile.write(json.dumps({"success": True, "products": all_prods, "total": len(all_prods)}, indent=2).encode("utf-8"))
            return

        # Serve static uploads if requested from api.py
        if clean_path.startswith("/uploads/"):
            fname = clean_path.replace("/uploads/", "")
            fpath = os.path.join(os.path.dirname(__file__), "public", "uploads", fname)
            if not os.path.exists(fpath):
                fpath = os.path.join(os.path.dirname(__file__), "test_images", fname)
            if os.path.exists(fpath):
                self.send_response(200)
                self._set_cors_headers()
                ct = "image/jpeg" if fpath.endswith((".jpg", ".jpeg")) else "image/png" if fpath.endswith(".png") else "application/octet-stream"
                self.send_header("Content-Type", ct)
                self.end_headers()
                with open(fpath, "rb") as f:
                    self.wfile.write(f.read())
                return

        # Weather endpoint for live customer UI display
        if clean_path in ["/api/weather", "/weather"]:
            try:
                from agents.weather_agent import run_weather_agent
                w_res = run_weather_agent("Vadodara")
                w_data = w_res.get("weather_data", {})
                temp = round(w_data.get("temperature", 28.0))
                cond = w_data.get("weather", "Sunny")
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "city": w_data.get("city", "Vadodara"),
                    "temperature": temp,
                    "condition": cond,
                    "display": f"{temp}°C • {cond}"
                }).encode("utf-8"))
                return
            except Exception:
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "city": "Vadodara",
                    "temperature": 28,
                    "condition": "Sunny",
                    "display": "28°C • Sunny"
                }).encode("utf-8"))
                return

        # Serve customer-facing index.html at root
        if clean_path in ["/", "/index.html"]:
            idx_path = os.path.join(os.path.dirname(__file__), "index.html")
            if os.path.exists(idx_path):
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(idx_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        if clean_path in ["/health", "/api/health", "/recommend", "/api/recommend", "/api/recommendations", "/api/inspiration/recommend"]:
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "ok",
                "service": "Moda Multi-Agent REST API & Staff Catalog Backend",
                "usage": "POST /recommend for styling, POST /api/staff/tag-image, POST /api/staff/save-product"
            }
            self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


    def do_POST(self):
        """Recommendation and Staff Catalog endpoints."""
        clean_path = self.path.split("?")[0]

        # 1. Staff: Tag Image endpoint
        if clean_path in ["/api/staff/tag-image", "/staff/tag-image"]:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body) if body else {}

                img_path = payload.get("image_path") or payload.get("image_url") or payload.get("filename")
                if not img_path:
                    raise ValueError("Field 'image_path' or 'filename' is required.")

                from services.staff_catalog import tag_product_image_for_review
                result = tag_product_image_for_review(img_path)

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "data": result}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        # 2. Staff: Save Product endpoint
        if clean_path in ["/api/staff/save-product", "/staff/save-product"]:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body) if body else {}

                from services.staff_catalog import save_staff_product
                saved_prod = save_staff_product(payload)

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "message": f"Product '{saved_prod['name']}' ({saved_prod['product_id']}) saved to shop inventory.",
                    "product": saved_prod
                }).encode("utf-8"))
                return
            except ValueError as ve:
                self.send_response(422)  # Unprocessable Entity for validation failures
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(ve)}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
                return

        # 3. Staff: Upload Image endpoint
        if clean_path in ["/api/staff/upload-image", "/staff/upload-image"]:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body) if body else {}

                fname = payload.get("filename", f"upload_{int(time.time())}.jpg")
                raw_b64 = payload.get("image_base64", "")
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[-1]

                import base64
                img_bytes = base64.b64decode(raw_b64)
                uploads_dir = os.path.join(os.path.dirname(__file__), "public", "uploads")
                os.makedirs(uploads_dir, exist_ok=True)
                target_path = os.path.join(uploads_dir, fname)
                with open(target_path, "wb") as f:
                    f.write(img_bytes)

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "filename": fname,
                    "image_path": target_path,
                    "image_url": f"/uploads/{fname}"
                }).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        # 4. Recommendation pipeline
        if clean_path in ["/recommend", "/api/recommend", "/api/recommendations", "/api/inspiration/recommend"]:
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                payload = json.loads(body) if body else {}

                prompt_val = payload.get("prompt", "").strip() if isinstance(payload.get("prompt"), str) else ""
                occasion = payload.get("occasion", "")
                item_type = payload.get("item_type", "")
                style = payload.get("style", "")
                city = payload.get("city", "Vadodara")

                if prompt_val:
                    user_prompt = prompt_val
                elif occasion or item_type:
                    parts = []
                    if occasion:
                        parts.append(occasion)
                    if item_type and item_type.lower() != "complete outfit":
                        parts.append(f"Looking for {item_type}")
                    elif item_type:
                        parts.append("Complete Outfit")
                    if style and style.lower() != "surprise me":
                        parts.append(f"Style: {style}")
                    user_prompt = " - ".join(parts)
                else:
                    user_prompt = payload.get("occasion") or "Smart casual outfit for Vadodara"

                if city and city.lower() not in user_prompt.lower():
                    user_prompt += f" in {city}"

                print(f"[LangGraph API] Received recommendation request: '{user_prompt}'")

                initial_state: AgentState = {
                    "user_prompt": user_prompt,
                    "next_agent": "",
                    "weather_data": {},
                    "wardrobe_items": [],
                    "execution_trace": [],
                    "final_response": ""
                }

                # Invoke LangGraph multi-agent supervisor graph
                final_state = app_graph.invoke(initial_state)

                witems = final_state.get("wardrobe_items", [])
                wdata = final_state.get("weather_data", {})
                raw_response = final_state.get("final_response", "")
                parsed_outfit = parse_outfit_from_text(raw_response, witems)

                outfit_options = final_state.get("outfit_options")
                if not outfit_options and witems:
                    from agents.stylist_agent import generate_outfit_options
                    outfit_options, _notice, _msg = generate_outfit_options(user_prompt, wdata, witems)
                outfit_options = outfit_options or []

                # Sanitized customer product cards (legacy format from Look 1)
                customer_products = []
                if outfit_options and outfit_options[0].get("items"):
                    for item in outfit_options[0]["items"]:
                        customer_products.append({
                            "name": item.get("name"),
                            "category": str(item.get("category", "")).capitalize(),
                            "image": item.get("image") or "/uploads/default.jpg",
                            "price": item.get("price"),
                            "available_sizes": item.get("sizes") or item.get("available_sizes") or [],
                            "stock_quantity": item.get("stock") or item.get("stock_quantity") or 0
                        })
                else:
                    for cat_key in ["top", "bottom", "dress", "shoes", "outerwear"]:
                        item = parsed_outfit.get(cat_key)
                        if item and isinstance(item, dict) and item.get("name") and not str(item.get("name", "")).lower().startswith("none"):
                            customer_products.append({
                                "name": item.get("name"),
                                "category": cat_key.capitalize(),
                                "image": item.get("image") or "/uploads/default.jpg",
                                "price": item.get("price"),
                                "available_sizes": item.get("available_sizes") or [],
                                "stock_quantity": item.get("stock_quantity") or 0
                            })

                temp_val = round(float(wdata.get("temperature", 28.0)), 1)
                cond_val = wdata.get("weather", "Sunny")

                is_notice = parsed_outfit.get("inventory_notice", False) or final_state.get("inventory_notice", False)
                is_partial = parsed_outfit.get("partial_inventory", False) or (len(outfit_options) > 0 and outfit_options[0].get("is_partial", False))
                cust_msg = parsed_outfit.get("customer_message", "") or final_state.get("customer_message", "")

                response_payload = {
                    "success": True,
                    "outfit_options": outfit_options,
                    "total_options": len(outfit_options),
                    "customer_products": customer_products,
                    "is_outfit": len(customer_products) > 1,
                    "inventory_notice": is_notice,
                    "partial_inventory": is_partial,
                    "customer_message": cust_msg,
                    "top": parsed_outfit.get("top"),
                    "bottom": parsed_outfit.get("bottom"),
                    "dress": parsed_outfit.get("dress"),
                    "outerwear": parsed_outfit.get("outerwear"),
                    "shoes": parsed_outfit.get("shoes"),
                    "weather": {
                        "city": wdata.get("city", "Vadodara"),
                        "temperature": temp_val,
                        "condition": cond_val,
                        "display": f"{round(temp_val)}°C • {cond_val}",
                        "rain_probability": wdata.get("rain_probability", 0),
                        "wind_speed": wdata.get("wind_speed", 10.0)
                    },
                    "recommended_outfit": parsed_outfit,
                    "full_recommendation": raw_response,
                    "execution_trace": final_state.get("execution_trace", []),
                    "retrieved_wardrobe_count": len(witems)
                }


                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response_payload).encode("utf-8"))

            except Exception as e:
                print(f"[LangGraph API Error] {e}")
                self.send_response(500)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_payload = {"success": False, "error": str(e)}
                self.wfile.write(json.dumps(error_payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def run_api_server(port: int = 5000):
    """Starts the HTTP API server."""
    server_address = ("", port)
    httpd = HTTPServer(server_address, LangGraphAPIHandler)
    print(f"🚀 Moda LangGraph API server running at http://localhost:{port}/recommend")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down LangGraph API server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    run_api_server(port=port)
