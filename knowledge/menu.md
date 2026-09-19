---
id: menu
type: menu
name: قائمة المنيو
language: ar
category: menu_knowledge_base
version: 11
last_updated: 2026-07-22
---

# Restaurant Information

## Restaurant Information: Restaurant

id: restaurant_information
type: restaurant
name: بريك

delivery_available: true
delivery_phone: 16099

## Restaurant Information: Working Hours

id: working_hours
type: hours
name: مواعيد العمل
opens: 10:00
closes: 04:00
note: يومياً طوال أيام الأسبوع

## Restaurant Information: Branch

id: branch_mohandessin
type: branch
name: المهندسين
category: cairo
address: المهندسين، شارع 9، امتداد ميدان النافورة، بجوار فرع اتصالات، أمام مونجيني

---

# Meals

## Meal: ربع فرخة بروستد

id: meal_quarter_broasted_chicken
type: meal
name: ربع فرخة بروستد
category: chicken

aliases:
- ربع فرخة
- بروستد ربع
- ربع بروستد

price:
  value: 135
  currency: EGP

available: true

ingredients:
- ورك فرخة بروستد
- بطاطس
- خبز
- ثومية صغيرة
- كاتشب

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
وجبة ربع فرخة بروستد تحتوي على:
- ورك فرخة بروستد
- بطاطس
- خبز
- ثومية صغيرة
- كاتشب

rules:
- لا تشمل صوص مجاني.
- لا تدعم اختيار صوص.

---

## Meal: وجبة ستربس 3 قطع

id: meal_strips_3
type: meal
name: وجبة ستربس 3 قطع
category: strips

aliases:
- ستربس 3
- ستريبس 3
- وجبة ستربس
- 3 ستربس

price:
  value: 150
  currency: EGP

available: true

ingredients:
- ثلاث قطع ستربس
- بطاطس
- خبز
- ثومية

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
وجبة ستربس 3 قطع تحتوي على:
- ثلاث قطع ستربس
- بطاطس
- خبز
- ثومية

rules:
- لا تشمل صوص مجاني.
- لا تدعم اختيار صوص.

---

## Meal: وجبة ستربس 5 قطع

id: meal_strips_5
type: meal
name: وجبة ستربس 5 قطع
category: strips

aliases:
- ستربس 5
- ستريبس 5
- 5 ستربس

price:
  value: 205
  currency: EGP

available: true

ingredients:
- خمس قطع ستربس
- بطاطس
- خبز
- ثومية

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
وجبة ستربس 5 قطع تحتوي على:
- خمس قطع ستربس
- بطاطس
- خبز
- ثومية

rules:
- لا تشمل صوص مجاني.
- لا تدعم اختيار صوص.

---

## Meal: وجبة بريك

id: meal_albaraka
type: meal
name: وجبة بريك
category: chicken

aliases:
- بريك
- وجبة بريك
- نصف فرخة
- نصف فرخة بروستد

price:
  value: 235
  currency: EGP

available: true

ingredients:
- نصف فرخة بروستد
- بطاطس
- خبز
- ثومية
- كول سلو
- كاتشب

sauce:
  supports_sauce: false
  free_quantity: 0
  available_count: 0
  available_sauces: []

description:
وجبة بريك تحتوي على:
- نصف فرخة بروستد
- بطاطس
- خبز
- ثومية
- كول سلو
- كاتشب

rules:
- لا تشمل صوص مجاني.
- لا تدعم اختيار صوص.

---

## Meal: فتة

id: meal_fatta
type: meal
name: فتة
category: rice

aliases:
- فتة
- الفتة
- فتة فراخ
- وجبة فتة

price:
  value: 160
  currency: EGP

available: true

ingredients:
- رز بسمتي
- ستربس
- كول سلو

sauce:
  supports_sauce: true
  free_quantity: 1
  available_count: 5
  available_sauces:
  - باربكيو
  - ثومية
  - رانش
  - سويت تشيلي
  - شيدر

description:
الفتة تحتوي على:
- رز بسمتي
- ستربس
- كول سلو

rules:
- تشمل اختيار صوص مجاني واحد.
- يمكن اختيار صوص واحد فقط.
- عدد الصوصات المتاحة: 5.

---

## Meal: بسمتيو

id: meal_basmatio
type: meal
name: بسمتيو
category: rice

aliases:
- بسمتيو
- بسمتي
- البسمتيو
- وجبة بسمتيو

price:
  value: 105
  currency: EGP

available: true

ingredients:
- رز بسمتي
- ستربس
- كول سلو

sauce:
  supports_sauce: true
  free_quantity: 1
  available_count: 5
  available_sauces:
  - باربكيو
  - ثومية
  - رانش
  - سويت تشيلي
  - شيدر

description:
البسمتيو يحتوي على:
- رز بسمتي
- ستربس
- كول سلو

rules:
- يشمل اختيار صوص مجاني واحد.
- يمكن اختيار صوص واحد فقط.
- عدد الصوصات المتاحة: 5.

---

# Add-ons

## Add-on: قطعة ستربس

id: addon_strip
type: addon
name: قطعة ستربس

aliases:
- قطعة زيادة
- ستربس زيادة
- قطعة ستريبس
- ستريبس زيادة

price:
  value: 35
  currency: EGP

available: true

description:
إضافة قطعة ستربس واحدة.

---

## Add-on: أرز بسمتي

id: addon_basmati
type: addon
name: أرز بسمتي

aliases:
- رز
- رز بسمتي
- بسمتي
- أرز

price:
  value: 25
  currency: EGP

available: true

description:
إضافة أرز بسمتي.

---

## Add-on: باكيت بطاطس

id: addon_fries
type: addon
name: باكيت بطاطس

aliases:
- بطاطس
- بطاطس زيادة
- باكيت فرايز
- فرايز

price:
  value: 35
  currency: EGP

available: true

description:
إضافة باكيت بطاطس.

---

## Add-on: ثومية كبير

id: addon_garlic
type: addon
name: ثومية كبير

aliases:
- ثومية
- ثومية زيادة
- ثومية كبيرة
- تومية

price:
  value: 15
  currency: EGP

available: true

description:
إضافة ثومية كبيرة.

---

## Add-on: عيش كايزر

id: addon_kaiser
type: addon
name: عيش كايزر

aliases:
- كايزر
- عيش
- خبز كايزر

price:
  value: 5
  currency: EGP

available: true

description:
إضافة عيش كايزر.

---

## Add-on: كول سلو

id: addon_coleslaw
type: addon
name: كول سلو

aliases:
- سلطة كول سلو
- كولسلو
- سلطة

price:
  value: 15
  currency: EGP

available: true

description:
إضافة كول سلو.

---

# Sauces

## Sauce: باربكيو

id: sauce_bbq
type: sauce
name: باربكيو

aliases:
- BBQ
- باربيكيو
- صوص باربكيو
- صوص BBQ

price:
  value: 25
  currency: EGP

available: true

description:
صوص باربكيو.

---

## Sauce: شيدر

id: sauce_cheddar
type: sauce
name: شيدر

aliases:
- تشيزي
- صوص شيدر
- صوص تشيزي
- شيدر تشيز

price:
  value: 35
  currency: EGP

available: true

description:
صوص شيدر.

---

## Sauce: رانش

id: sauce_ranch
type: sauce
name: رانش

aliases:
- صوص رانش
- رانش صوص

price:
  value: 15
  currency: EGP

available: true

description:
صوص رانش.

---

## Sauce: سويت تشيلي

id: sauce_sweet_chili
type: sauce
name: سويت تشيلي

aliases:
- سويت شيلي
- صوص سويت تشيلي
- صوص سويت شيلي
- سويت تشيلي صوص

price:
  value: 15
  currency: EGP

available: true

description:
صوص سويت تشيلي.

---

## Sauce: ثومية

id: sauce_garlic
type: sauce
name: ثومية

aliases:
- صوص ثومية
- تومية
- صوص تومية
- ثوميه

price:
  value: 15
  currency: EGP

available: true

description:
صوص ثومية.

---

# Drinks

## Drink: مشروب

id: drink_soft
type: drink
name: مشروب

aliases:
- بيبسي
- كانز
- مشروب غازي
- بيبسي كانز
- سفن
- ميرندا

price:
  value: 25
  currency: EGP

available: true

description:
مشروب غازي.

---

## Drink: مياه

id: drink_water
type: drink
name: مياه

aliases:
- مية
- زجاجة مياه
- مياه معدنية

price:
  value: 10
  currency: EGP

available: true

description:
زجاجة مياه.

---

# Extras

## Extra: شريطي فرايز

id: extra_strip_fries
type: extra
name: شريطي فرايز

aliases:
- شريطي
- ستريبس فرايز
- فرايز
- بطاطس شريطي
- شريطي بطاطس

price:
  value: 25
  currency: EGP

available: true

description:
إضافة شريطي فرايز.

---

# Combo Upgrade

## Combo: كومبو

id: combo_upgrade
type: combo_upgrade
name: كومبو

aliases:
- كومبو
- ترقية كومبو
- Upgrade
- كومبو أبجريد
- كومبو ابجريد

price:
  value: 50
  currency: EGP

available: true

includes:
- باكيت بطاطس
- مشروب

description:
يمكن ترقية أي وجبة إلى كومبو.

rules:
- ترقية الكومبو متاحة مع الوجبات.
- تشمل باكيت بطاطس ومشروب.

---

# Restaurant Rules

## Sauce Rules

id: sauce_rules
type: rules
name: قواعد الصوص

description:
Only these meals support free sauce:
- فتة:
  - free_sauce_quantity: 1
- بسمتيو:
  - free_sauce_quantity: 1

All other meals:
- لا تدعم اختيار صوص.
- لا تشمل صوص مجاني.

---

# Sauce Availability

## Sauce Availability: Available Sauces

id: sauce_availability
type: sauce_availability
name: توافر الصوصات

description:
Available sauces:
- باربكيو
- ثومية
- رانش
- سويت تشيلي
- شيدر

Sauce prices:
- باربكيو: 25 جنيه
- شيدر: 35 جنيه
- رانش: 15 جنيه
- سويت تشيلي: 15 جنيه
- ثومية: 15 جنيه

---

# Menu Categories

## Menu Categories: Categories

id: menu_categories
type: menu_categories
name: أقسام المنيو

categories:
- 🍗 الوجبات
- ➕ الإضافات
- 🥫 الصوصات
- 🥤 المشروبات
- 🍟 الإضافات الجانبية
- ⭐ ترقية الكومبو

---

# Search Keywords

## Search Keywords: Meals

id: search_keywords_meals
type: keywords
name: كلمات بحث الوجبات
category: meals

terms:
- فتة
- الفتة
- فتة فراخ
- بسمتيو
- بسمتي
- البسمتيو
- ربع فرخة
- ربع فرخة بروستد
- بروستد
- وجبة بريك
- بريك
- ستربس
- ستريبس
- ستربس 3
- ستربس 5

---

## Search Keywords: Sauces

id: search_keywords_sauces
type: keywords
name: كلمات بحث الصوصات
category: sauces

terms:
- صوص
- الصوصات
- اختيار صوص
- صوص مجاني
- صوصات
- باربكيو
- BBQ
- رانش
- ثومية
- تومية
- شيدر
- تشيزي
- سويت تشيلي

---

## Search Keywords: Menu Requests

id: search_keywords_menu_requests
type: keywords
name: كلمات بحث الطلبات
category: menu_requests

terms:
- المنيو
- قائمة الطعام
- الأسعار
- وريني المنيو
- اعرض المنيو
- عندكم إيه
- ايه عندكم
- عايز أطلب
- كل الأصناف
- كل المنتجات

---

## Search Keywords: Add-ons

id: search_keywords_addons
type: keywords
name: كلمات بحث الإضافات
category: addons

terms:
- قطعة ستربس
- ستربس زيادة
- باكيت بطاطس
- بطاطس زيادة
- ثومية كبير
- ثومية زيادة
- كول سلو
- أرز بسمتي
- رز
- عيش كايزر

---

## Search Keywords: Combo

id: search_keywords_combo
type: keywords
name: كلمات بحث الكومبو
category: combo

terms:
- كومبو
- ترقية كومبو
- Upgrade
- كومبو أبجريد
- الكومبو
- أزود كومبو

---

# Retrieval Notes

## Retrieval Notes: Meal Sauce Lookup

id: retrieval_notes_sauce_lookup
type: retrieval_notes
name: ملاحظات البحث عن الصوص

description:
When a customer asks about sauce:
1. Identify the exact meal.
2. Use only that meal's sauce fields.
3. Do not use other meal information.

fields:
- supports_sauce
- free_sauce_quantity
- available_sauces

---

# Response Rules

## Response Rules: Unknown Information

id: response_rules_unknown
type: response_rules
name: قواعد الرد - معلومات غير موجودة

description:
If information is unavailable, reply exactly:
عذراً، هذه المعلومة غير موجودة في قاعدة بيانات المطعم.

---

## Response Rules: Recommendations

id: response_rules_recommendations
type: response_rules
name: قواعد الرد - التوصيات

description:
No meal recommendations exist.
If asked for:
- أفضل وجبة
- أشهر وجبة
- أرشحلي وجبة

Reply exactly:
عذراً، لا توجد توصيات محددة في قاعدة بيانات المطعم.

---

# Knowledge Source

## Knowledge Source: Menu

id: knowledge_source_menu
type: knowledge_source
name: مصدر قاعدة المعرفة

description:
All information in this file belongs to مطعم بريك menu information.
Only use the provided restaurant information when answering customer questions.

# Reindex Test
