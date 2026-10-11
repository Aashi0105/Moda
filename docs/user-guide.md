# Moda User Guide

Quick-start job aids and FAQ for shop staff | Version 1.1 (draft)

> **Status:** draft. Not yet tested with real users.

Moda is an AI styling assistant for fashion shops. It helps staff in two ways: a **Styling Assistant** that builds outfit options for customers from items that are actually in stock, and a **Staff Catalog Portal** where staff add products to the inventory, with AI help for tagging.

**Who this is for:** shop staff who style customers, and staff who maintain the product catalogue.

## 1. The two screens

| Screen | How to open it | Use it to |
|---|---|---|
| Styling Assistant | Home page, the Stylist tab | Choose an occasion and what the customer is looking for, then get up to three outfit options with prices, sizes and remaining stock. |
| Staff Catalog Portal | Open `/staff`, or use the Staff link on the home page | Upload product photos, review AI tags, enter SKU, price, stock and sizes, and see the live inventory. |

## 2. Job aid: get outfit options for a customer

| Step | What to do | What you should see |
|---|---|---|
| 1 | Open the home page and go to the Stylist tab. | The occasion selector, the category chips and the weather panel. |
| 2 | Choose the occasion: Birthday, Casual, Office / Meeting, Date Night, Brunch, Party, Wedding, Formal Event or Everyday. | The occasion is selected. |
| 3 | Choose what the customer is looking for: Complete Outfit, Top, Bottom, Dress or Shoes. | The chip is highlighted. |
| 4 | Check the weather shown. It loads automatically and defaults to Vadodara. | Current conditions for the location. |
| 5 | Click **AI Style Suggest**. | Up to three looks (Look 1, Look 2, Look 3) or All Looks. |
| 6 | Read each look: the items, individual prices in rupees, available sizes, remaining stock and the total bundle price. | A complete outfit with its price. |

**What the three outfit types mean**

| Outfit type | Pieces |
|---|---|
| One-Piece Dress | Dress and footwear |
| Classic Separates | Top, bottom and footwear |
| Layered Statement | Top, bottom, outerwear and footwear |

**Tip:** if Moda shows an inventory notice instead of outfits, the stock cannot support that request. Try another occasion or category, or check the catalogue for missing items.

## 3. Job aid: add a new product in the Staff Catalog Portal

| Step | What to do | What you should see |
|---|---|---|
| 1 | Open `/staff`. | The catalogue form and the live inventory table. |
| 2 | Upload the garment photo (drag and drop works). | The photo appears and Moda starts tagging it. |
| 3 | Wait for the AI tags: category, subcategory, colour, pattern, formality and season. | Suggested tags with confidence scores. |
| 4 | Review the tags. Anything marked **Needs Review** must be checked. | Tags under 70% confidence, or with missing details, are flagged. |
| 5 | Correct any wrong tag. Your choice always overrides the AI suggestion. | The tag shows your selection. |
| 6 | Enter the SKU (format `MODA-xxxx`), the price, the stock quantity and the available sizes (XS, S, M, L, XL or One Size). | The commercial fields are filled in. |
| 7 | Click **Confirm & Save Product to Shop Inventory**. | The item appears in the live inventory table with its stock count. |

**Moda will reject a product if:** the category and subcategory do not match (for example Top with Jeans), the price is negative, or the SKU already exists.

## 4. Job aid: keep stock accurate

- Update the stock quantity when items are sold or restocked.
- Items with zero stock are never recommended, so a wrong zero will hide a product from customers.
- Check the live inventory table at the start of each week for items that look wrong.

## 5. How to read a recommendation

- **Look cards:** every item is a real product from the catalogue, with its price, sizes and remaining stock.
- **Bundle price:** the total for the whole outfit, calculated by the system, not estimated by the AI.
- **Inventory notice:** shown when the stock cannot support the request. Moda does not invent products.

## 6. Frequently asked questions

**Why does Moda only suggest items we have in stock?**
Moda builds outfits only from verified catalogue items. Items with zero stock are excluded, and when stock cannot support a request it shows an inventory notice instead of inventing products.

**Where does the weather come from?**
Moda looks up live conditions through the Open-Meteo weather service. By default it uses Vadodara.

**How accurate is the AI tagging?**
It is a first draft. Each tag has a confidence score, and Moda flags anything under 70% confidence or with missing details as Needs Review. Staff should always check those.

**Can I change a tag the AI chose?**
Yes. Your selection always takes precedence over the AI suggestion.

**What does Needs Review mean?**
Moda was not confident about one or more tags. A staff member should check and confirm them before saving.

**Why was my product rejected when I saved it?**
Check the message. The most common causes are a category and subcategory that do not match, a negative price, or a SKU that already exists.

**Why is an item not appearing in recommendations?**
Check its stock quantity first, since zero-stock items are excluded. Then check its category, formality and season tags.

**What are Look 1, Look 2 and Look 3?**
Three different outfit options built from the same request, each using one of the outfit types (dress, separates or layered).

**What happens if the weather or AI service is slow?**
Moda uses timeouts and fallbacks so the screen does not freeze. Wait a moment and try again.

**Who do I ask for help?**
Ask your shop's Moda champion first. They can raise issues with the person maintaining the system.

## 7. Troubleshooting

| What you see | Likely cause | What to do |
|---|---|---|
| Inventory notice instead of outfits | Not enough in-stock items for that request | Try another occasion or category; add missing items to the catalogue |
| Product rejected: invalid pairing | Category and subcategory do not match | Choose a valid subcategory for the category |
| Product rejected: duplicate SKU | The SKU already exists | Use a unique `MODA-xxxx` SKU or edit the existing product |
| Product rejected: negative price | Price typed incorrectly | Enter a price of zero or more |
| Needs Review badge | Low confidence or missing tag | Check and correct the tags, then save |
| An item never appears in outfits | Stock is zero or tags are wrong | Fix the stock and tags |
| Page is slow | Weather or AI response is taking time | Wait briefly and retry; report it if it keeps happening |

Report anything unclear or broken to your shop's Moda champion so the guide and the product can be improved.
