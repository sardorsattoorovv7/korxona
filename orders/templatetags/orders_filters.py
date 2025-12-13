from django import template
from django.utils import timezone
from datetime import datetime
from decimal import Decimal  # 👈 BU QATORNI QO'SHING
register = template.Library()

@register.filter
def filter_expired_orders(orders_queryset):
    """
    Berilgan QuerySet ichidan muddati o'tgan va 'BAJARILDI' statusida bo'lmagan
    buyurtmalarni filterlaydi.
    """
    now = timezone.now()
    
    # Muddati o'tgan buyurtmalarni filtrlash: 
    # deadline maydoni to'ldirilgan BO'LISHI va hozirgi vaqtdan KICHIK BO'LISHI
    # hamda statusi 'BAJARILDI' ga teng BO'LMASLIGI kerak.
    expired_orders = orders_queryset.filter(
        deadline__isnull=False,  # Muddati o'rnatilgan bo'lishi kerak
        deadline__lt=now         # Muddat hozirgi vaqtdan o'tgan bo'lishi kerak
    ).exclude(status='BAJARILDI').exclude(status='RAD_ETILDI')
    
    return expired_orders

@register.simple_tag
def get_current_time():
    """ Hozirgi vaqtni qaytaradi. Shablon ichida foydalanish uchun. """
    return timezone.now()

@register.filter(name='times')
def times(value, arg):
    """Qiymatni berilgan argumentga ko'paytiradi."""
    try:
        return Decimal(value) * Decimal(arg)
    except (ValueError, TypeError, AttributeError):
        return ''
    

@register.filter
def sub(value, arg):
    """
    Argumentdan qiymatni ayiradi.
    Foydalanish: {{ material.quantity|sub:material.min_stock_level }}
    """
    try:
        # Decimal yoki floatlar bilan ishlash uchun konvertatsiya
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return '' # Xatolik yuz bersa bo'sh qoldirish

@register.filter
def times(value, arg):
    """
    Argumentga qiymatni ko'paytirish.
    Foydalanish: {{ material.quantity|times:material.price_per_unit }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''
    
from django import template

register = template.Library()

@register.filter
def mul(value, arg):
    """ value * arg ni qaytaradi """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def divide(value, arg):
    """ value / arg ni qaytaradi """
    try:
        # Bo'linuvchi 0 ga teng bo'lsa, xatolikni oldini olamiz
        if arg == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return ''
