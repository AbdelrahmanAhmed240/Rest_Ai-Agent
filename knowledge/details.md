----
id: restaurant
type: restaurant
name: بريك
language: ar
category: restaurant_information
version: 4
last_updated: 2026-07-22

---

# Contact
## Contact: Phone
id: contact_phone
type: contact
name: رقم الدليفري والطلبات
value: 16099

# Hours
## Hours: Working Hours
id: working_hours
type: hours
name: مواعيد العمل
opens: 10:00
closes: 04:00
note: يومياً طوال أيام الأسبوع

# Social Media
## Social Media: Facebook
id: social_facebook
type: social_media
name: صفحة مطعم بريك على فيسبوك
platform: Facebook
url: https://www.facebook.com/RestaurantPage/

# Branches
## Branch: فرع المهندسين
id: branch_mohandessin
type: branch
name: فرع المهندسين
category: cairo
address: 45 شارع البطل أحمد عبد العزيز، من شارع جامعة الدول العربية.

## Branch: فرع المقطم
id: branch_mokattam
type: branch
name: فرع المقطم
category: cairo
address: شارع 9، امتداد ميدان النافورة، بجوار فرع اتصالات، أمام مونجيني.

## Branch: فرع الشيراتون
id: branch_sheraton
type: branch
name: فرع الشيراتون
category: cairo
address: 43 مساكن الشيراتون، المنطقة الأولى، شارع أنقرة.

## Branch: فرع جليم
id: branch_glim
type: branch
name: فرع جليم
category: alexandria
aliases:

- شارع الإذاعة
address: 30 شارع الإذاعة، جليم.

## Branch: فرع المندرة
id: branch_mandara
type: branch
name: فرع المندرة
category: alexandria
address: طريق الجيش، امتداد شارع مسجد عبد الحليم محمود، أمام كافيه سانتوس.

## Branch: فرع كامب شيزار
id: branch_camp_caesar
type: branch
name: فرع كامب شيزار
category: alexandria
aliases:

- كامب
address: كامب شيزار، على البحر، بجوار كافيتيريا والي.

## Branch: فرع سموحة 1
id: branch_smouha1
type: branch
name: فرع سموحة 1
category: alexandria
address: تعاونيات سموحة، شارع مسجد حاتم، خلف المديرية.

## Branch: فرع سموحة 2
id: branch_smouha2
type: branch
name: فرع سموحة 2
category: alexandria
address: السوق التجاري، شارع مسجد حاتم.

## Branch: فرع بحري
id: branch_bahary
type: branch
name: فرع بحري
category: alexandria
address: 19 طريق 26 يوليو، بجوار جيلاتي الصعيدي.

## Branch: فرع سيدي بشر
id: branch_sidi_bishr
type: branch
name: فرع سيدي بشر
category: alexandria
address: شارع العيسوي، أمام شركة الكهرباء.

## Branch: فرع المحروسة
id: branch_mahrousa
type: branch
name: فرع المحروسة
category: alexandria
address: طريق الجيش، بجانب نفق المحروسة مباشرة، وفندق المحروسة.

# Delivery
## Delivery: Delivery Policy
id: delivery_policy
type: delivery
name: سياسة التوصيل
available: true
areas: جميع مناطق القاهرة
duration: 30 إلى 45 دقيقة
fee: 25 ج.م
minimum_order: لا يوجد

# Payment
## Payment: Delivery Payment
id: payment_delivery
type: payment
name: الدفع عند التوصيل
context: delivery
methods:

- Cash

## Payment: Pickup Payment
id: payment_pickup
type: payment
name: الدفع عند الاستلام من الفرع
context: pickup
methods:

- Cash
- Visa

# Keywords
## Keywords: Branch Keywords
id: keywords_branches
type: keywords
name: كلمات بحث الفروع
category: branches
terms:

- الفروع
- فرع
- فروع القاهرة
- فروع اسكندرية
- فرع جليم
- فرع سموحة
- فرع المقطم
- فرع المهندسين
- branch
- branches
