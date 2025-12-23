from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group 
from django.contrib import messages 
from django.contrib.auth import get_user_model 
from django.db.models import Q, Sum 
from orders.models import Worker, Order     
from datetime import date, timedelta, datetime
from django.http import HttpResponse, JsonResponse
import csv 
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Material
from django.db.models import Sum, F
from django.conf import settings

# AUDIT LOG UCHUN IMPORTLAR
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import LogEntry, CHANGE, DELETION, ADDITION 

from .models import Order, Notification, Worker 
from .forms import OrderForm, StartImageUploadForm, FinishImageUploadForm

from django.db.models import Count, Case, When, IntegerField


User = get_user_model()

# --- Yordamchi Funksiya: Foydalanuvchi qaysi guruhda ekanligini tekshirish ---
def is_in_group(user, group_name):
    """Foydalanuvchi berilgan guruhda mavjudligini tekshiradi."""
    if user.is_anonymous:
        return False
        
    if user.is_superuser and group_name == 'Glavniy Admin':
        return True
        
    try:
        return user.groups.filter(name=group_name).exists()
    except Group.DoesNotExist:
        return False

# --- Yangi: Kuzatuvchi funksiyalari ---
def is_observer(user):
    """Foydalanuvchi kuzatuvchi guruhida ekanligini tekshiradi."""
    if user.is_anonymous:
        return False
    return is_in_group(user, 'Kuzatuvchi')

def is_observer_or_above(user):
    """Kuzatuvchi yoki undan yuqori darajadagi foydalanuvchilarni tekshiradi."""
    return (
        is_observer(user) or 
        is_in_group(user, 'Glavniy Admin') or 
        is_in_group(user, 'Menejer') or 
        is_in_group(user, "Ishlab Chiqarish Boshlig'i") or
        user.is_superuser
    )

# ----------------------------------------------------------------------
# 💡 YORDAMCHI FUNKSIYA: MUDDAT BUZILISHINI TEKSHIRISH
# ----------------------------------------------------------------------
def check_and_create_overdue_alerts(order):
    """
    Berilgan buyurtma uchun muddat o'tgan bo'lsa va ogohlantirish yuborilmagan bo'lsa,
    Notification yaratadi.
    """
    if not order.deadline or order.deadline > timezone.now():
        return False 
    
    if order.status in ['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']:
        return False 

    if hasattr(order, 'deadline_breach_alert_sent') and order.deadline_breach_alert_sent:
        return False 

    admin_users = User.objects.filter(
        Q(is_superuser=True) | 
        Q(groups__name='Glavniy Admin') | 
        Q(groups__name="Ishlab Chiqarish Boshlig'i")
    ).distinct()
    
    message = (
        f"🚨 URGENT: Buyurtma #{order.order_number} ning muddati {order.deadline.strftime('%d-%m %H:%M')} da O'TIB KETDI. "
        f"Status: {order.get_status_display()}."
    )
    
    for admin in admin_users:
        Notification.objects.create(
            user=admin,
            order=order,
            message=message
        )
    
    if hasattr(order, 'deadline_breach_alert_sent'):
        order.deadline_breach_alert_sent = True
        order.save(update_fields=['deadline_breach_alert_sent'])
    
    return True

# --- Yordamchi Funksiya: Hisobotni ko'rishga ruxsatni tekshirish ---
def is_report_viewer(user):
    """Admin, Menejer va Ishlab Chiqarish Boshlig'iga ruxsat beradi."""
    from django.conf import settings
    
    # Agar foydalanuvchi tizimga kirmagan bo'lsa, avtomatik rad etamiz
    if not user.is_authenticated:
        return False
        
    return (
        is_in_group(user, 'Glavniy Admin') or 
        is_in_group(user, 'Menejer') or 
        is_in_group(user, "Ishlab Chiqarish Boshlig'i")
    )

# --- Yangi: Hisobotlar uchun kengaytirilgan ruxsat tekshiruvi ---
def is_report_viewer_or_observer(user):
    """Admin, Menejer, Ishlab Chiqarish Boshlig'i yoki Kuzatuvchiga ruxsat beradi."""
    return is_report_viewer(user) or is_observer(user)

# ----------------------------------------------------------------------
# YANGI: RASM YUKLASH FUNKSIYASI
# ----------------------------------------------------------------------
@require_POST
@csrf_exempt
@login_required
def upload_order_image(request):
    """
    Usta tomonidan rasm yuklash uchun AJAX endpoint
    """
    try:
        order_id = request.POST.get('order_id')
        upload_type = request.POST.get('upload_type')  # 'qabul', 'start', 'finish'
        comment = request.POST.get('comment', '')
        
        if not order_id or not upload_type:
            return JsonResponse({'success': False, 'error': 'Ma\'lumotlar yetarli emas'})
        
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Buyurtma topilmadi'})
        
        # Ruxsatni tekshirish
        is_worker = is_in_group(request.user, 'Usta')
        is_assigned_worker = order.assigned_workers.filter(user=request.user).exists()
        
        if not is_worker or not is_assigned_worker:
            return JsonResponse({'success': False, 'error': 'Sizga ruxsat yo\'q'})
        
        # Rasm yuklash turiga qarab formani tanlash
        if upload_type == 'start':
            form = StartImageUploadForm(request.POST, request.FILES, instance=order)
            if order.status == 'TASDIQLANDI' and not order.start_image:
                if form.is_valid():
                    order = form.save(commit=False)
                    order.status = 'USTA_QABUL_QILDI'
                    order.start_image_uploaded_at = timezone.now()
                    if comment:
                        order.comment = f"{order.comment or ''}\n\nUsta izohi ({timezone.now().strftime('%Y-%m-%d %H:%M')}): {comment}"
                    order.save()
                    return JsonResponse({
                        'success': True, 
                        'message': 'Boshlash rasmi muvaffaqiyatli yuklandi',
                        'new_status': order.status
                    })
                else:
                    return JsonResponse({
                        'success': False, 
                        'error': form.errors.as_text()
                    })
            else:
                return JsonResponse({'success': False, 'error': 'Boshlash rasm yuklash uchun holat mos emas'})
                
        elif upload_type == 'finish':
            form = FinishImageUploadForm(request.POST, request.FILES, instance=order)
            if order.status in ['USTA_BOSHLA', 'ISHDA'] and not order.finish_image:
                if form.is_valid():
                    order = form.save(commit=False)
                    order.status = 'USTA_TUGATDI'
                    order.worker_finished_at = timezone.now()
                    order.finish_image_uploaded_at = timezone.now()
                    if comment:
                        order.comment = f"{order.comment or ''}\n\nUsta izohi ({timezone.now().strftime('%Y-%m-%d %H:%M')}): {comment}"
                    order.save()
                    return JsonResponse({
                        'success': True, 
                        'message': 'Tugatish rasmi muvaffaqiyatli yuklandi',
                        'new_status': order.status
                    })
                else:
                    return JsonResponse({
                        'success': False, 
                        'error': form.errors.as_text()
                    })
            else:
                return JsonResponse({'success': False, 'error': 'Tugatish rasm yuklash uchun holat mos emas'})
        else:
            return JsonResponse({'success': False, 'error': 'Noto\'g\'ri yuklash turi'})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# ----------------------------------------------------------------------
# MAXSUS LOGIN VIEW
# ----------------------------------------------------------------------
class CustomLoginView(LoginView):
    template_name = 'orders/login.html'
    redirect_authenticated_user = True
    success_url = reverse_lazy('order_list') 

# ----------------------------------------------------------------------
# ASOSIY SAHIFA / RO'YXAT
# ----------------------------------------------------------------------

@login_required 
def order_list(request):
    
    # Guruhlar tekshiruvi
    is_glavniy_admin = request.user.is_superuser or is_in_group(request.user, 'Glavniy Admin')
    is_production_boss = is_in_group(request.user, "Ishlab Chiqarish Boshlig'i")
    is_manager_or_confirmer = is_in_group(request.user, 'Menejer/Tasdiqlovchi')
    is_worker = is_in_group(request.user, 'Usta')
    is_observer = is_in_group(request.user, 'Kuzatuvchi')

    # Filtr parametri
    filter_type = request.GET.get('filter', 'all')  # all, completed, in_progress, overdue
    
    # ASOSIY BUYURTMALAR (parent_order=None)
    main_orders = Order.objects.filter(parent_order__isnull=True).order_by('-created_at')
    
    # CHILD BUYURTMALAR - PANEL va UGUL
    all_child_orders = Order.objects.filter(parent_order__isnull=False).order_by('-created_at')
    
    # Panel child orderlar (product_name ichida "panel" so'zi borlar)
    panel_child_orders = all_child_orders.filter(
        Q(product_name__icontains='panel') | 
        Q(product_name__icontains='панель') |
        Q(product_name__icontains='панел')
    )
    
    # Ugul child orderlar (product_name ichida "ugul" so'zi borlar)
    ugul_child_orders = all_child_orders.filter(
        Q(product_name__icontains='ugul') | 
        Q(product_name__icontains='угол') |
        Q(product_name__icontains='уголь')
    )
    
    # Boshqa child orderlar
    other_child_orders = all_child_orders.exclude(
        Q(product_name__icontains='panel') | 
        Q(product_name__icontains='панель') |
        Q(product_name__icontains='панел') |
        Q(product_name__icontains='ugul') | 
        Q(product_name__icontains='угол') |
        Q(product_name__icontains='уголь')
    )
    
    # Hammasini vaqt bo'yicha ko'rsatadi (asosiy va child birlashtirilgan)
    orders = Order.objects.all().order_by('-created_at')
    
    # Filtrlash
    now = timezone.now()
    if filter_type == 'completed':
        # Tayyor buyurtmalar
        main_orders = main_orders.filter(status__in=['TAYYOR', 'BAJARILDI'])
        panel_child_orders = panel_child_orders.filter(status__in=['TAYYOR', 'BAJARILDI'])
        ugul_child_orders = ugul_child_orders.filter(status__in=['TAYYOR', 'BAJARILDI'])
        other_child_orders = other_child_orders.filter(status__in=['TAYYOR', 'BAJARILDI'])
        orders = orders.filter(status__in=['TAYYOR', 'BAJARILDI'])
    elif filter_type == 'in_progress':
        # Jarayondagi buyurtmalar - FAQAT MUDDATI O'TMAGANLAR
        main_orders = main_orders.exclude(status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=now)
        )
        panel_child_orders = panel_child_orders.exclude(status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=now)
        )
        ugul_child_orders = ugul_child_orders.exclude(status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=now)
        )
        other_child_orders = other_child_orders.exclude(status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=now)
        )
        orders = orders.exclude(status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']).filter(
            Q(deadline__isnull=True) | Q(deadline__gte=now)
        )
    elif filter_type == 'overdue':
        # Muddati o'tgan buyurtmalar - FAQAT JARAYONDAGI VA MUDDATI O'TGANLAR
        main_orders = main_orders.filter(
            deadline__lt=now
        ).exclude(
            status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
        )
        panel_child_orders = panel_child_orders.filter(
            deadline__lt=now
        ).exclude(
            status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
        )
        ugul_child_orders = ugul_child_orders.filter(
            deadline__lt=now
        ).exclude(
            status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
        )
        other_child_orders = other_child_orders.filter(
            deadline__lt=now
        ).exclude(
            status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
        )
        orders = orders.filter(
            deadline__lt=now
        ).exclude(
            status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
        )
    
    # Filterlash mantigi
    should_filter = True 

    if is_glavniy_admin or is_production_boss or is_manager_or_confirmer or is_observer:
        should_filter = False 
    
    if is_worker:
        if not (is_glavniy_admin or is_production_boss or is_manager_or_confirmer or is_observer):
            try:
                # Ustaga tayinlangan barcha buyurtmalar ro'yxatini olamiz
                orders = orders.filter(
                    assigned_workers__user=request.user, 
                ).exclude(
                    status='RAD_ETILDI'
                ).distinct().order_by('-created_at')
                
                main_orders = main_orders.filter(
                    assigned_workers__user=request.user, 
                ).exclude(
                    status='RAD_ETILDI'
                ).distinct().order_by('-created_at')
                
                panel_child_orders = panel_child_orders.filter(
                    assigned_workers__user=request.user, 
                ).exclude(
                    status='RAD_ETILDI'
                ).distinct().order_by('-created_at')
                
                ugul_child_orders = ugul_child_orders.filter(
                    assigned_workers__user=request.user, 
                ).exclude(
                    status='RAD_ETILDI'
                ).distinct().order_by('-created_at')
                
                other_child_orders = other_child_orders.filter(
                    assigned_workers__user=request.user, 
                ).exclude(
                    status='RAD_ETILDI'
                ).distinct().order_by('-created_at')
                
                if not orders.exists():
                    messages.info(request, "Sizga tayinlangan buyurtmalar topilmadi.")

            except Exception:
                orders = orders.none() 
                main_orders = main_orders.none()
                panel_child_orders = panel_child_orders.none()
                ugul_child_orders = ugul_child_orders.none()
                other_child_orders = other_child_orders.none()
                messages.warning(request, "Buyurtmalarni yuklashda xato: Usta profili noto'g'ri bog'langan bo'lishi mumkin.")
            
            should_filter = True

    if should_filter and not is_worker:
        pass

    # Muddat buzilishini tekshirish
    if is_glavniy_admin or is_production_boss:
        overdue_orders = main_orders.filter(
            deadline__lt=timezone.now(),
            status__in=['TASDIQLANDI', 'USTA_QABUL_QILDI', 'USTA_BOSHLA', 'ISHDA', 'KIRITILDI']
        )
        for order in overdue_orders:
            check_and_create_overdue_alerts(order)

    user_notifications = Notification.objects.filter(user=request.user, is_read=False)[:5]
    
    # STATISTIKA
    total_orders = main_orders.count()  # Faqat asosiy buyurtmalar
    completed_orders = main_orders.filter(status__in=['TAYYOR', 'BAJARILDI']).count()
    
    # Jarayondagi buyurtmalar soni - FAQAT MUDDATI O'TMAGANLAR
    in_progress_orders = main_orders.exclude(
        status__in=['TAYYOR', 'BAJARILDI', 'RAD_ETILDI']
    ).filter(
        Q(deadline__isnull=True) | Q(deadline__gte=now)
    ).count()
    
    # Muddati o'tgan buyurtmalar soni
    overdue_orders_count = main_orders.filter(
        deadline__lt=now
    ).exclude(
        status__in=['BAJARILDI', 'RAD_ETILDI', 'TAYYOR']
    ).count()
    
    # Child orderlar statistikasi
    all_child_orders_count = all_child_orders.count()
    panel_child_count = panel_child_orders.count()
    ugul_child_count = ugul_child_orders.count()
    other_child_count = other_child_orders.count()
    
    panel_completed = panel_child_orders.filter(status__in=['TAYYOR', 'BAJARILDI']).count()
    ugul_completed = ugul_child_orders.filter(status__in=['TAYYOR', 'BAJARILDI']).count()
    
    context = {
        'orders': orders,
        'main_orders': main_orders,
        'panel_child_orders': panel_child_orders,
        'ugul_child_orders': ugul_child_orders,
        'other_child_orders': other_child_orders,
        'is_glavniy_admin': is_glavniy_admin,
        'is_manager': is_manager_or_confirmer, 
        'is_production_boss': is_production_boss,
        'is_worker': is_worker,
        'is_observer': is_observer,
        'notifications': user_notifications, 
        'now': timezone.now(),
        'filter_type': filter_type,
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'in_progress_orders': in_progress_orders,
        'overdue_orders_count': overdue_orders_count,
        'all_child_orders_count': all_child_orders_count,
        'panel_child_count': panel_child_count,
        'ugul_child_count': ugul_child_count,
        'other_child_count': other_child_count,
        'panel_completed': panel_completed,
        'ugul_completed': ugul_completed,
        'is_storekeeper': request.user.username.lower() == 'omborchi' or 'store' in request.user.username.lower(),
    }
    return render(request, 'orders/order_list.html', context)

from django.db.models import Sum, Count
from django.shortcuts import render
from .models import Worker, Order

def rankings_view(request):
    """Ustalar reytingi sahifasi"""
    # Bajarilgan buyurtmalar soni va kvadrat metr bo'yicha ustalarni hisoblash
    workers_list = Worker.objects.annotate(
        total_finished=Count('orders', filter=models.Q(orders__status='TUGATILDI')),
        total_kvadrat=Sum('orders__panel_kvadrat', filter=models.Q(orders__status='TUGATILDI'))
    ).order_by('-total_kvadrat') # Eng ko'p kvadrat metr qilganlar birinchi chiqadi

    context = {
        'workers': workers_list,
    }
    return render(request, 'orders/rankings.html', context)
# ----------------------------------------------------------------------
# BUYURTMA TAHSILOTLARI
# ----------------------------------------------------------------------
@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    
    # Ruxsatlarni tekshirish
    is_glavniy_admin = request.user.is_superuser or is_in_group(request.user, 'Glavniy Admin')
    is_manager = is_in_group(request.user, 'Menejer/Tasdiqlovchi')
    is_production_boss = is_in_group(request.user, "Ishlab Chiqarish Boshlig'i")
    is_worker = is_in_group(request.user, 'Usta') 
    is_observer = is_in_group(request.user, 'Kuzatuvchi')  # ✅ YANGI
    
    # ✅ KUZATUVCHI UCHUN ALTERNATIV RENDER
    if is_observer:
        context = {
            'order': order,
            'order_form': None,
            'is_glavniy_admin': False,
            'is_manager': False,
            'is_production_boss': False,
            'is_worker': False,
            'is_observer': True,
            'start_image_form': None,
            'finish_image_form': None,
            'readonly': True,
        }
        return render(request, 'orders/order_detail.html', context)
    
    # Usta tayinlanganligini TO'G'RI tekshirish
    is_assigned_worker = False
    if is_worker:
        try:
            # Worker modeli orqali tekshirish
            worker_profile = request.user.worker_profile
            is_assigned_worker = order.assigned_workers.filter(pk=worker_profile.pk).exists()
        except Worker.DoesNotExist:
            # Agar worker profile yo'q bo'lsa
            is_assigned_worker = False
        except Exception as e:
            print(f"Xatolik: {e}")
            is_assigned_worker = False

    # DEBUG: Konsolga chiqaramiz
    print(f"User: {request.user}")
    print(f"Is worker: {is_worker}")
    print(f"Is assigned worker: {is_assigned_worker}")
    print(f"Assigned workers: {list(order.assigned_workers.all())}")

    # Ruxsat tekshiruvi
    if is_worker and not is_assigned_worker and not is_production_boss:
        messages.error(request, "Siz faqat o'zingizga tayinlangan buyurtma tafsilotlarini ko'rishingiz mumkin.")
        return redirect('order_list')
    
    is_assigned_worker = False
    if is_worker:
        try:
            if order.assigned_workers.filter(user=request.user).exists():
                is_assigned_worker = True
        except Exception:
            is_assigned_worker = False

    if is_worker and not is_assigned_worker and not is_production_boss:
        messages.error(request, "Siz faqat o'zingizga tayinlangan buyurtma tafsilotlarini ko'rishingiz mumkin.")
        return redirect('order_list')

    
    start_image_form = None
    finish_image_form = None
    order_form = None
    
    # Admin/Manager/Boss uchun asosiy tahrirlash formasi
    is_admin_or_manager = is_glavniy_admin or is_manager or is_production_boss
    if is_admin_or_manager:
        order_form = OrderForm(request.POST or None, request.FILES or None, instance=order)
        
        if request.method == 'POST' and 'upload_type' not in request.POST:
            if order_form.is_valid():
                order_form.save()
                messages.success(request, "Buyurtma ma'lumotlari muvaffaqiyatli yangilandi.")
                return redirect('order_detail', pk=order.pk)
            else:
                messages.error(request, "Buyurtma ma'lumotlarini saqlashda xatolik yuz berdi.")
        
    
    # GET so'rovi: Rasm yuklash formalarini tayyorlash
    if is_assigned_worker:
        if not order.start_image and order.status == 'TASDIQLANDI': 
            start_image_form = StartImageUploadForm(instance=order) 
            
        if not order.finish_image and order.status in ['USTA_BOSHLA', 'ISHDA']:
            finish_image_form = FinishImageUploadForm(instance=order) 

    # POST so'rovi kelganda (Rasm yuklash)
    if request.method == 'POST' and is_assigned_worker:
        
        upload_type = request.POST.get('upload_type') 
        
        # Boshlash Rasmi yuklash
        if upload_type == 'start_image':
            form = StartImageUploadForm(request.POST, request.FILES, instance=order) 
            
            if order.status == 'TASDIQLANDI' and not order.start_image:
                if form.is_valid() and request.FILES.get('start_image'): 
                    order = form.save(commit=False)
                    order.status = 'USTA_QABUL_QILDI'
                    order.save(update_fields=['start_image', 'status']) 
                    messages.success(request, "Boshlash Rasmi muvaffaqiyatli yuklandi. Buyurtma **Qabul Qilindi**.")
                else:
                    messages.error(request, "Boshlash Rasmida xato yoki rasm tanlanmadi.")
            else:
                 messages.warning(request, "Boshlash rasm yuklash uchun holat mos emas.")
                
        # Tugatish Rasmi yuklash
        elif upload_type == 'finish_image':
            form = FinishImageUploadForm(request.POST, request.FILES, instance=order)
            
            if order.status in ['USTA_BOSHLA', 'ISHDA'] and not order.finish_image:
                if form.is_valid() and request.FILES.get('finish_image'):
                    order = form.save(commit=False)
                    order.status = 'USTA_TUGATDI'
                    order.worker_finished_at = timezone.now()
                    order.save(update_fields=['finish_image', 'status', 'worker_finished_at']) 
                    messages.success(request, "Tugatish Rasmi muvaffaqiyatli yuklandi. Buyurtma **Usta Yakunladi**.")
                else:
                    messages.error(request, "Tugatish Rasmida xato yoki rasm tanlanmadi.")
            else:
                messages.warning(request, "Tugatish rasm yuklash uchun holat mos emas.")
        
        return redirect('order_detail', pk=order.pk)

    context = {
        'order': order,
        'order_form': order_form,
        'is_glavniy_admin': is_glavniy_admin,
        'is_manager': is_manager,
        'is_production_boss': is_production_boss,
        'is_worker': is_worker,
        'is_observer': is_observer,  # ✅ YANGI
        'is_assigned_worker': is_assigned_worker,
        'start_image_form': start_image_form, 
        'finish_image_form': finish_image_form, 
    }
    
    return render(request, 'orders/order_detail.html', context)

# ----------------------------------------------------------------------
# USTA HARAKATLARI FUNKSIYALARI
# ----------------------------------------------------------------------
@login_required
@user_passes_test(lambda u: is_in_group(u, 'Usta') or u.is_superuser, login_url='/login/')
def order_worker_accept(request, pk):
    """Usta buyurtmani qabul qilish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not request.user.is_superuser and not order.assigned_workers.filter(user=request.user).exists():
        messages.error(request, "Siz bu buyurtmaga tayinlanmagansiz.")
        return redirect('order_list')

    if order.status == 'TASDIQLANDI':
        if not order.start_image:
             messages.error(request, "Ishni qabul qilishdan oldin, **Boshlanish Rasmini** yuklashingiz kerak.")
             return redirect('order_detail', pk=order.pk)

        order.status = 'USTA_QABUL_QILDI'
        order.save(update_fields=['status'])
        messages.success(request, f"Buyurtma #{order.order_number} ustalar tomonidan qabul qilindi. Endi 'Boshlash' tugmasini bosing.")
    else:
        messages.warning(request, f"Buyurtma #{order.order_number} faqat 'Tasdiqlandi' statusida qabul qilinishi mumkin.")
        
    return redirect('order_list')

@login_required
@user_passes_test(lambda u: is_in_group(u, 'Usta') or u.is_superuser, login_url='/login/')
def order_worker_start(request, pk):
    """Usta ishni boshlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not request.user.is_superuser and not order.assigned_workers.filter(user=request.user).exists():
        messages.error(request, "Siz bu operatsiyani bajarishga ruxsat etilmagansiz.")
        return redirect('order_list')

    if order.status == 'USTA_QABUL_QILDI':
        order.status = 'USTA_BOSHLA'
        order.worker_started_at = timezone.now() 
        order.save(update_fields=['status', 'worker_started_at'])
        messages.success(request, f"Buyurtma #{order.order_number} bo'yicha ish boshlandi. Status: USTA BOSHLADI.")
    else:
        messages.warning(request, f"Ishni boshlash uchun buyurtma 'Usta Qabul Qildi' statusida bo'lishi kerak.")
        
    return redirect('order_list')
@login_required
@user_passes_test(lambda u: is_in_group(u, 'Usta') or u.is_superuser, login_url='/login/')
def order_worker_finish(request, pk):
    """Usta ishni yakunlash va avtomatik ravishda keyingi bosqich ustalari uchun buyurtma ochish."""
    
    # 1. Kuzatuvchi (Observer) tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)

    # 2. Huquqlarni tekshirish (faqat biriktirilgan usta yoki superuser)
    if not request.user.is_superuser and not order.assigned_workers.filter(user=request.user).exists():
        messages.error(request, "Siz bu operatsiyani bajarishga ruxsat etilmagansiz.")
        return redirect('order_list')

    # 3. Rasm yuklanganligini tekshirish
    if not order.finish_image:
         messages.error(request, "Ishni tugatishdan oldin, yakuniy rasm (Tugatish Rasmi) yuklashingiz kerak.")
         return redirect('order_detail', pk=order.pk)
        
    # 4. Statusni yangilash
    if order.status in ['USTA_BOSHLA', 'ISHDA']: 
        current_time = timezone.now()
        order.status = 'USTA_TUGATDI'
        order.worker_finished_at = current_time 
        
        # Muddatdan o'tib ketgan bo'lsa ogohlantirish
        if order.deadline and current_time > order.deadline:
            # Agar funksiya mavjud bo'lsa chaqiriladi
            if 'check_and_create_overdue_alerts' in globals():
                check_and_create_overdue_alerts(order)
            messages.warning(request, f"⚠️ Buyurtma #{order.order_number} muddatidan kech yakunlandi.")
            
        order.save(update_fields=['status', 'worker_finished_at'])

        # ================================================================
        # YANGI ZANJIRSIMON ALGORITM (List usta -> Panel/Ugol usta)
        # ================================================================
        
        # Agar hozirgi foydalanuvchi "List usta" guruhida bo'lsa
        if is_in_group(request.user, "List usta"):
            # Keyingi bosqich ustalari (Panel va Ugol) guruhlarini bazadan topamiz
            next_workers = Worker.objects.filter(
                Q(user__groups__name="Panel usta") | Q(user__groups__name="Ugol usta")
            )
            
            if next_workers.exists():
                # Yangi order raqami (masalan: ORD-100 bo'lsa, ORD-100-PU bo'ladi)
                new_order_number = f"{order.order_number}-PU"
                
                # Agar bunaqa raqamli buyurtma hali ochilmagan bo'lsa (dublikat bo'lmasligi uchun)
                if not Order.objects.filter(order_number=new_order_number).exists():
                    new_order = Order.objects.create(
                        order_number=new_order_number,
                        material=order.material,
                        quantity=order.quantity,
                        drawings_pdf=order.drawings_pdf, # List usta ishlatgan chizmani o'tkazamiz
                        status='TASDIQLANDI',           # Avtomatik tasdiqlangan holatda
                        created_by=order.created_by,
                        deadline=timezone.now() + timedelta(days=1), # 1 kun muddat
                        notes=f"List usta #{order.order_number} ishini yakunlagani uchun avtomatik yaratildi."
                    )
                    
                    # Topilgan barcha Panel va Ugol ustalarni yangi buyurtmaga biriktiramiz
                    for worker in next_workers:
                        new_order.assigned_workers.add(worker)
                        
                        # Har biriga bildirishnoma yuboramiz
                        Notification.objects.create(
                            user=worker.user,
                            order=new_order,
                            message=f"Yangi ish: List usta #{order.order_number} chizmasini bitirdi. Panel/Ugol bosqichini boshlang."
                        )
                    
                    messages.success(request, "Panel va Ugol ustalari uchun avtomatik buyurtma yaratildi.")
        # ================================================================

        messages.success(request, f"Buyurtma #{order.order_number} yakunlandi.")
    else:
        messages.warning(request, "Ishni yakunlash uchun buyurtma 'Usta Boshladi' yoki 'Ishda' statusida bo'lishi kerak.")
        
    return redirect('order_list')

# ----------------------------------------------------------------------
# YANGI: USTALAR PANELI FUNKSIYALARI
# ----------------------------------------------------------------------
@login_required
@user_passes_test(lambda u: is_in_group(u, 'Usta') or u.is_superuser or 
                   is_in_group(u, "Ishlab Chiqarish Boshlig'i") or 
                   is_in_group(u, 'Kuzatuvchi'), login_url='/login/')  # ✅ YANGI
def worker_panel(request):
    """
    Ustalar paneli - barcha ustalar ro'yxati
    """
    # Faqat admin, ishlab chiqarish boshliqlari va kuzatuvchilar ko'ra oladi
    is_glavniy_admin = request.user.is_superuser or is_in_group(request.user, 'Glavniy Admin')
    is_production_boss = is_in_group(request.user, "Ishlab Chiqarish Boshlig'i")
    is_observer = is_in_group(request.user, 'Kuzatuvchi')  # ✅ YANGI
    
    if not (is_glavniy_admin or is_production_boss or is_observer):  # ✅ YANGI
        messages.error(request, "Sizda bu sahifani ko'rish uchun ruxsat yo'q.")
        return redirect('order_list')
    
    # Barcha ustalarni olish
    workers = Worker.objects.all().select_related('user')
    
    # Har bir usta uchun statistikani hisoblash
    for worker in workers:
        worker.completed_orders_count = Order.objects.filter(
            assigned_workers=worker,
            status__in=['TAYYOR', 'BAJARILDI']
        ).count()
        
        worker.total_kvadrat = Order.objects.filter(
            assigned_workers=worker,
            status__in=['TAYYOR', 'BAJARILDI']
        ).aggregate(Sum('panel_kvadrat'))['panel_kvadrat__sum'] or 0
    
    context = {
        'workers': workers,
        'is_glavniy_admin': is_glavniy_admin,
        'is_production_boss': is_production_boss,
        'is_observer': is_observer,  # ✅ YANGI
    }
    
    return render(request, 'orders/worker_panel.html', context)

@login_required
@user_passes_test(lambda u: is_in_group(u, 'Usta') or u.is_superuser or 
                   is_in_group(u, "Ishlab Chiqarish Boshlig'i") or 
                   is_in_group(u, 'Kuzatuvchi'), login_url='/login/')  # ✅ YANGI
def worker_orders(request, worker_id):
    """
    Muayyan ustaning barcha buyurtmalari
    """
    worker = get_object_or_404(Worker, id=worker_id)
    
    # Ruxsatni tekshirish
    is_glavniy_admin = request.user.is_superuser or is_in_group(request.user, 'Glavniy Admin')
    is_production_boss = is_in_group(request.user, "Ishlab Chiqarish Boshlig'i")
    is_worker_self = request.user == worker.user
    is_observer = is_in_group(request.user, 'Kuzatuvchi')  # ✅ YANGI
    
    if not (is_glavniy_admin or is_production_boss or is_worker_self or is_observer):  # ✅ YANGI
        messages.error(request, "Sizda bu sahifani ko'rish uchun ruxsat yo'q.")
        return redirect('order_list')
    
    # Filtrlash parametrlari
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    status_filter = request.GET.get('status', '')
    
    # Ustaning buyurtmalari
    orders = Order.objects.filter(assigned_workers=worker).order_by('-created_at')
    
    # Filtrlash
    if start_date:
        orders = orders.filter(created_at__gte=start_date)
    if end_date:
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        orders = orders.filter(created_at__lt=end_datetime)
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    # Statistikani hisoblash
    total_orders = orders.count()
    completed_orders = orders.filter(status__in=['TAYYOR', 'BAJARILDI']).count()
    total_kvadrat = orders.filter(status__in=['TAYYOR', 'BAJARILDI']).aggregate(
        Sum('panel_kvadrat')
    )['panel_kvadrat__sum'] or 0
    
    context = {
        'worker': worker,
        'orders': orders,
        'total_orders': total_orders,
        'completed_orders': completed_orders,
        'total_kvadrat': total_kvadrat,
        'start_date': start_date,
        'end_date': end_date,
        'status_filter': status_filter,
        'is_glavniy_admin': is_glavniy_admin,
        'is_production_boss': is_production_boss,
        'is_worker_self': is_worker_self,
        'is_observer': is_observer,  # ✅ YANGI
    }
    
    return render(request, 'orders/worker_orders.html', context)

# ----------------------------------------------------------------------
# QOLGAN FUNKSIYALAR
# ----------------------------------------------------------------------
@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def order_create(request):
    """Buyurtma yaratish - soddalashtirilgan versiya"""
    
    if request.method == 'POST':
        form = OrderForm(request.POST, request.FILES)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            
            # 🔴 PANEL VA UGOL UCHUN AVTOMATIK TASDIQLASH
            worker_type = form.cleaned_data.get('worker_type', 'LIST')
            
            if worker_type in ['PANEL', 'UGOL']:
                order.status = 'TASDIQLANDI'  # Avtomatik tasdiqlangan
                status_message = "avtomatik tasdiqlandi"
            else:
                order.status = 'KIRITILDI'  # List va Eshik uchun
                status_message = "kiritildi"
            
            # 🔴 MODEL VALIDATIONNI O'TKAZIB YUBORISH
            try:
                order.save()
            except ValidationError as e:
                # Agar validatsiya xatosi bo'lsa, uni ignore qilish
                order.status = 'TASDIQLANDI' if worker_type in ['PANEL', 'UGOL'] else 'KIRITILDI'
                order.save(force_insert=True)
            
            form.save_m2m()
            
            messages.success(request, 
                f"✅ Buyurtma №{order.order_number} {status_message}! "
                f"Ish turi: {order.get_worker_type_display()}"
            )
            
            return redirect('order_list')
    else:
        form = OrderForm()
    
    return render(request, 'orders/order_create.html', {'form': form})

@login_required
@login_required
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        form = OrderForm(request.POST, request.FILES, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, "Buyurtma tahrirlandi.")
            return redirect('order_detail', pk=order.pk)
    else:
        form = OrderForm(instance=order)
        # Tahrirlashda ham faqat kerakli ustalarni ko'rsatish
        form.fields['assigned_workers'].queryset = Worker.objects.filter(
            Q(user__groups__name="List usta") | Q(user__groups__name="Eshik usta")
        ).distinct()
    return render(request, 'orders/order_create.html', {'form': form, 'is_edit': True})


@login_required
def order_confirm(request, pk):
    """2-Bosqich: Buyurtmani tasdiqlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not is_in_group(request.user, 'Menejer/Tasdiqlovchi'): 
        messages.error(request, "Sizda bu buyurtmani tasdiqlash uchun ruxsat yo'q.")
        return redirect('order_list')

    if order.status == 'KIRITILDI':
        order.status = 'TASDIQLANDI'
        order.save()
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: KIRITILDI -> TASDIQLANDI"
        )
        
        messages.success(request, f"Buyurtma №{order.order_number} Tasdiqlandi.")
        
        if order.created_by:
            Notification.objects.create(
                user=order.created_by,
                order=order,
                message=f"Siz kiritgan buyurtma №{order.order_number} Muvaffaqiyatli Tasdiqlandi."
            )
        
        try:
            boss_group = Group.objects.get(name="Ishlab Chiqarish Boshlig'i")
            for boss in boss_group.user_set.all():
                Notification.objects.create(
                    user=boss,
                    order=order,
                    message=f"Yangi buyurtma №{order.order_number} Tasdiqlandi. Ishlab chiqarishni boshlashingiz mumkin."
                )
        except Group.DoesNotExist:
            messages.warning(request, "Ishlab Chiqarish Boshlig'i guruhi topilmadi.")

        if order.assigned_workers.exists():
            for worker in order.assigned_workers.all():
                Notification.objects.create(
                    user=worker.user,
                    order=order,
                    message=f"Tayinlangan buyurtma №{order.order_number} Tasdiqlandi! Ishni boshlashingiz mumkin."
                )
            
    else:
        messages.warning(request, "Bu buyurtma allaqachon tasdiqlangan yoki boshqa bosqichda.")
        
    return redirect('order_list')

@login_required
def order_reject(request, pk):
    """Buyurtmani Rad Etish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not is_in_group(request.user, 'Menejer/Tasdiqlovchi'): 
        messages.error(request, "Sizda bu buyurtmani rad etish uchun ruxsat yo'q.")
        return redirect('order_list')

    if order.status == 'KIRITILDI':
        order.status = 'RAD_ETILDI'
        order.save()
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: KIRITILDI -> RAD ETILDI"
        )
        
        messages.error(request, f"Buyurtma №{order.order_number} **Rad Etildi**.")
        
        if order.created_by:
            Notification.objects.create(
                user=order.created_by,
                order=order,
                message=f"Siz kiritgan buyurtma №{order.order_number} Menejer tomonidan **RAD ETILDI**."
            )

        if order.assigned_workers.exists():
            for worker in order.assigned_workers.all():
                Notification.objects.create(
                    user=worker.user,
                    order=order,
                    message=f"Sizga tayinlangan buyurtma №{order.order_number} RAD ETILDI."
                )
        
    else:
        messages.warning(request, "Rad etishni faqat 'Kiritildi' statusidagi buyurtmadan boshlash mumkin.")
        
    return redirect('order_list')

@login_required
def order_start_production(request, pk):
    """3-Bosqich: Ishlab chiqarishga berish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not is_in_group(request.user, "Ishlab Chiqarish Boshlig'i"):
        messages.error(request, "Ishlab chiqarishni boshlash uchun ruxsat yo'q.")
        return redirect('order_list')

    if order.status == 'TASDIQLANDI':
        order.status = 'ISHDA'
        order.save()
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: TASDIQLANDI -> ISHDA"
        )
        
        messages.info(request, f"Buyurtma №{order.order_number} ishlab chiqarishga berildi.")
        
        if order.assigned_workers.exists():
            for worker in order.assigned_workers.all():
                Notification.objects.create(
                    user=worker.user,
                    order=order,
                    message=f"Buyurtma №{order.order_number} ISHGA TUSHDI. O'z ishingizni boshlashingiz mumkin."
                )
        
    else:
        messages.warning(request, "Ishlab chiqarishni faqat Tasdiqlangan buyurtmadan boshlash mumkin.")
        
    return redirect('order_list')
@login_required
def order_finish(request, pk):
    """4-Bosqich: Buyurtmani yakunlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not is_in_group(request.user, "Ishlab Chiqarish Boshlig'i"):
        messages.error(request, "Buyurtmani yakunlash uchun ruxsat yo'q.")
        return redirect('order_list')

    if order.status in ['ISHDA', 'USTA_TUGATDI']:
        order.status = 'TAYYOR'
        order.save()
        
        # 🔴 Agar List usta ishini tugatgan bo'lsa, Panel va Ugol ustalar uchun yangi buyurtmalar yaratish
        if order.worker_type == 'LIST':
            try:
                order.create_panel_ugol_orders()
                messages.info(request, 
                    f"List usta ishini tugatdi. Panel va Ugol ustalariga yangi buyurtmalar avtomatik yaratildi."
                )
            except Exception as e:
                messages.warning(request, f"Panel/Ugol buyurtmalarini yaratishda xato: {e}")
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: {order.get_status_display()} -> TAYYOR"
        )
        
        messages.success(request, f"Buyurtma №{order.order_number} **Tayyor** deb belgilandi. Jarayon yakunlandi.")
        
        # Manager/Tasdiqlovchi guruhiga bildirishnoma yuborish
        try:
            manager_group = Group.objects.get(name='Menejer/Tasdiqlovchi') 
            for manager in manager_group.user_set.all():
                Notification.objects.create(
                    user=manager,
                    order=order,
                    message=f"Buyurtma №{order.order_number} Tayyor! Yakuniy Bajarildi deb belgilash talab qilinadi."
                )
        except Group.DoesNotExist:
            pass
            
        # Buyurtmaga biriktirilgan ishchilarga bildirishnoma yuborish
        if order.assigned_workers.exists():
            for worker in order.assigned_workers.all():
                Notification.objects.create(
                    user=worker.user,
                    order=order,
                    message=f"Sizning buyurtmangiz №{order.order_number} Tayyor deb belgilandi."
                )

    else:
        messages.warning(request, "Buyurtma Tayyor deb belgilanishi uchun u ishlab chiqarish jarayonida bo'lishi kerak.")
        
    return redirect('order_list')

@login_required
def order_complete(request, pk):
    """Yakuniy bosqich: Buyurtmani to'liq Bajarildi deb belgilash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if not is_in_group(request.user, 'Menejer/Tasdiqlovchi'): 
        messages.error(request, "Buyurtmani yakunlash uchun ruxsat yo'q.")
        return redirect('order_list')

    if order.status == 'TAYYOR':
        order.status = 'BAJARILDI' 
        order.save()
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: TAYYOR -> BAJARILDI (Yakuniy amal)"
        )
        
        messages.success(request, f"Buyurtma №{order.order_number} **BAJARILDI** deb belgilandi. Jarayon to'liq yakunlandi.")
        
        if order.created_by:
            Notification.objects.create(
                user=order.created_by,
                order=order,
                message=f"Siz kiritgan buyurtma №{order.order_number} Muvaffaqiyatli **BAJARILDI**."
            )
        
    else:
        messages.warning(request, "Buyurtma Bajarildi deb belgilanishi uchun u avval 'Tayyor' bo'lishi kerak.")
        
    return redirect('order_list')

@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def order_create(request):
    """1-Bosqich: Buyurtmani yuklash/kiritish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    if request.method == 'POST':
        form = OrderForm(request.POST, request.FILES)
        if form.is_valid():
            order = form.save(commit=False)
            order.created_by = request.user
            order.status = 'KIRITILDI' 
            
            # 🔴 Ish turini saqlash
            worker_type = form.cleaned_data.get('worker_type', 'LIST')
            order.worker_type = worker_type
            
            order.save()
            form.save_m2m() 
            
            LogEntry.objects.log_action(
                user_id=request.user.id,
                content_type_id=ContentType.objects.get_for_model(order).pk,
                object_id=order.pk,
                object_repr=str(order),
                action_flag=ADDITION,
                change_message=f"Yangi buyurtma kiritildi: №{order.order_number} (Ish turi: {order.get_worker_type_display()})"
            )

            messages.success(request, 
                f"Buyurtma №{order.order_number} muvaffaqiyatli kiritildi. "
                f"Ustalar tayinlandi. Ish turi: {order.get_worker_type_display()}"
            )
            
            # 🔴 Notification yuborish
            try:
                manager_group = Group.objects.get(name='Menejer/Tasdiqlovchi') 
                for manager in manager_group.user_set.all():
                    Notification.objects.create(
                        user=manager,
                        order=order,
                        message=f"Yangi buyurtma kiritildi: №{order.order_number}. "
                                f"Ish turi: {order.get_worker_type_display()}. Tasdiqlash talab qilinadi."
                    )
            except Group.DoesNotExist:
                messages.warning(request, "Menejer/Tasdiqlovchi guruhi topilmadi.")

            if order.assigned_workers.exists():
                for worker in order.assigned_workers.all():
                    Notification.objects.create(
                        user=worker.user,
                        order=order,
                        message=f"Buyurtma №{order.order_number} sizga tayinlandi. "
                                f"Ish turi: {order.get_worker_type_display()}. Tasdiqlanishini kuting."
                    )
            
            return redirect('order_list')
    else:
        form = OrderForm()
    
    return render(request, 'orders/order_create.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def order_delete(request, pk):
    """Buyurtmani Glavniy Admin tomonidan o'chirish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        order_num = order.order_number
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk, 
            object_repr=str(order),
            action_flag=DELETION,
            change_message=f"Buyurtma №{order_num} tizimdan o'chirildi."
        )
        
        order.delete()
        messages.error(request, f"Buyurtma №{order_num} tizimdan butunlay **O'CHIRILDI**.")
        return redirect('order_list')
        
    return render(request, 'orders/order_confirm_delete.html', {'order': order})

from decimal import Decimal
from datetime import datetime, timedelta
from django.db.models import Q
from django.utils import timezone
# ... (boshqa importlar)

@login_required
@user_passes_test(is_report_viewer_or_observer, login_url='/login/')
def weekly_report_view(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # Vaqt zonasidan xabardor sanalarni saqlash uchun o'zgaruvchilar
    start_datetime_aware = None
    end_datetime_aware = None

    # ----------------------------------------------------------------------
    # 💡 MUHIM TUZATISH: Sanani TZ-Aware qilish
    # ----------------------------------------------------------------------

    if start_date_str:
        try:
            # 1. Tanlangan sanani Naive Datetime obyektiga o'tkazamiz (00:00:00)
            start_datetime_naive = datetime.strptime(start_date_str, '%Y-%m-%d')
            # 2. Uni loyihaning TIME_ZONE zonasidan xabardor qilamiz (Masalan, Toshkent vaqti)
            start_datetime_aware = timezone.make_aware(start_datetime_naive)
        except ValueError:
             messages.error(request, "Boshlanish sana formati noto'g'ri.")
             start_date_str = None # Noto'g'ri bo'lsa filtrlashni to'xtatamiz

    if end_date_str:
        try:
            # 1. Tanlangan sanani Naive Datetime obyektiga o'tkazamiz (+1 kun)
            end_datetime_naive = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
            # 2. Uni loyihaning TIME_ZONE zonasidan xabardor qilamiz
            end_datetime_aware = timezone.make_aware(end_datetime_naive)
        except ValueError:
            messages.error(request, "Tugash sana formati noto'g'ri.")
            end_date_str = None
            
    # ----------------------------------------------------------------------
    # 1. Umumiy Buyurtmalar (created_at bo'yicha) filtrlash
    # ----------------------------------------------------------------------
    orders = Order.objects.all().select_related('created_by')
    filter_q = Q()
    
    if start_datetime_aware:
        # created_at__gte ni TZ-aware qiymat bilan solishtiramiz
        filter_q &= Q(created_at__gte=start_datetime_aware) 
    if end_datetime_aware:
        # created_at__lt ni TZ-aware qiymat bilan solishtiramiz
        filter_q &= Q(created_at__lt=end_datetime_aware) 
            
    report_orders = orders.filter(filter_q).order_by('-created_at')
    
    # ... (Umumiy statistikani hisoblash)
    
    # ----------------------------------------------------------------------
    # 2. Ustalar Ish Faoliyati Hisoboti (worker_finished_at bo'yicha)
    # ----------------------------------------------------------------------
    worker_report_orders = Order.objects.filter(
        status__in=['TAYYOR', 'BAJARILDI']
    ).filter(
        worker_finished_at__isnull=False 
    ).prefetch_related(
        'assigned_workers__user'
    ) 
    
    worker_filter_q = Q()
    # Yuqorida tayyorlangan TZ-aware obyektlarni qayta ishlatamiz!
    if start_datetime_aware:
        worker_filter_q &= Q(worker_finished_at__gte=start_datetime_aware)
    if end_datetime_aware:
        worker_filter_q &= Q(worker_finished_at__lt=end_datetime_aware)
            
    worker_report_orders = worker_report_orders.filter(worker_filter_q)
    
    # ... (Qolgan loop va kontekst mantig'i)
    
    # Kontekstni yangilash
    context = {
        # ... (boshqa kontekstlar)
        # Template uchun sanalarni string formatida qaytarish
        'start_date': start_date_str,
        'end_date': end_date_str,
        # ...
    }

    return render(request, 'orders/weekly_report_view.html', context)
# orders/views.py

from django.shortcuts import render, redirect 
from django.contrib import messages
from django.contrib.auth.decorators import login_required
# ... (Boshqa importlar qolaversin) ...

# from .forms import MaterialInflowForm, MaterialOutflowForm # Bularni o'chirib tashlaymiz
from .forms import MaterialTransactionForm # YANGI formani import qilamiz

# ... (material_sarfi_report funksiyasi qolaversin) ...

# ===================================================================
# 🔄 YAGONA VIEW: MATERIAL HARAKATINI YARATISH
# ===================================================================

from .forms import (
    OrderForm, 
    StartImageUploadForm, 
    FinishImageUploadForm, 
    OrderStatusForm, 
    MaterialTransactionForm,)
import json
# views.py

# views.py
from django.db import transaction as db_transaction
from django.contrib import messages
import json

# views.py
# views.py - material_transaction_create view ni yangilash
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction as db_transaction
import json
from .forms import MaterialTransactionForm
from .models import Material

import json
import uuid  # ⬅️ Unikal kod uchun shart
from django.db import transaction as db_transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

@login_required
def material_transaction_create(request):
    """Material kirim/chiqim tranzaksiyasini yaratish."""
    
    if request.method == 'POST':
        form = MaterialTransactionForm(request.POST)
        
        if form.is_valid():
            try:
                with db_transaction.atomic():
                    transaction_obj = form.save(commit=False)
                    transaction_obj.performed_by = request.user
                    
                    material = transaction_obj.material
                    quantity = transaction_obj.quantity_change
                    transaction_type = transaction_obj.transaction_type

                    # 🔴 PARTIYA BARCODE YARATISH MANTIQI
                    # Agar Kirim bo'lsa va checkbox bosilgan bo'lsa
                    create_barcode = request.POST.get('create_batch_barcode') == 'on'
                    if transaction_type == 'IN' and create_barcode:
                        # Unikal va qisqaroq kod yaratish
                        new_code = f"P-{uuid.uuid4().hex[:8].upper()}"
                        transaction_obj.transaction_barcode = new_code
                    
                    # Material qoldig'ini yangilash
                    if transaction_type == 'IN':
                        material.quantity += quantity
                        message_type = "✅ Kirim"
                    else:  # OUT
                        if material.quantity < quantity:
                            raise ValueError(f"Omborda yetarli qoldiq yo'q! (Mavjud: {material.quantity})")
                        material.quantity -= quantity
                        message_type = "📤 Chiqim"
                    
                    # Saqlash
                    material.save()
                    transaction_obj.save()
                    
                    success_msg = f"{message_type} saqlandi. Qoldiq: {material.quantity}"
                    if transaction_obj.transaction_barcode:
                        success_msg += f" | Partiya kodi: {transaction_obj.transaction_barcode}"
                        
                    messages.success(request, success_msg)
                    return redirect('material_list')
                    
            except Exception as e:
                messages.error(request, f"❌ Xatolik: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    
    # GET so'rovi uchun qolgan qism (mavjud kodingiz)
    else:
        form = MaterialTransactionForm()
    
    materials = Material.objects.all().select_related('category')
    material_data = {
        str(mat.id): {
            'name': mat.name,
            'unit': mat.unit.upper(),
            'quantity': float(mat.quantity),
            'category': mat.category.name if mat.category else 'Kategoriyasiz',
        } for mat in materials
    }
    
    return render(request, 'orders/material_transaction_create.html', {
        'form': form,
        'material_data_json': json.dumps(material_data, ensure_ascii=False),
    })


# 🔴 YANGI: Material yaratish view
@login_required
def material_create(request):
    """Yangi material yaratish."""
    if request.method == 'POST':
        form = MaterialForm(request.POST)
        if form.is_valid():
            material = form.save()
            messages.success(request, f"✅ Material '{material.name}' muvaffaqiyatli yaratildi.")
            return redirect('material_list')
    else:
        form = MaterialForm()
    
    context = {'form': form}
    return render(request, 'orders/material_form.html', context)


# 🔴 YANGI: Material tahrirlash view
@login_required
def material_edit(request, pk):
    """Materialni tahrirlash."""
    material = get_object_or_404(Material, pk=pk)
    
    if request.method == 'POST':
        form = MaterialForm(request.POST, instance=material)
        if form.is_valid():
            material = form.save()
            messages.success(request, f"✅ Material '{material.name}' muvaffaqiyatli yangilandi.")
            return redirect('material_list')
    else:
        form = MaterialForm(instance=material)
    
    context = {'form': form, 'material': material}
    return render(request, 'orders/material_form.html', context)

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import F, ExpressionWrapper, DecimalField, Sum, Q, Avg, Count, IntegerField, Case, When
from django.db.models.functions import Coalesce # Coalesce uchun import
from datetime import timedelta
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal # Decimal ishlatish uchun

# Modellar importi (Material va MaterialTransaction)
from .models import Material, MaterialTransaction 
# Eslatma: Agar modellar boshqa joyda bo'lsa, uni yuqoriga qo'ying

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q, F, DecimalField, IntegerField, Count, Avg, ExpressionWrapper, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator
from decimal import Decimal # DecimalField uchun kerak

# Material va MaterialTransaction modellarini import qiling (agar yuqorida bo'lmasa)
# from .models import Material, MaterialTransaction 

@login_required
def material_list(request):
    """
    Omborxona materiallari va tranzaksiyalarini ko'rsatish:
    Barcode va to'g'rilangan related_name bilan.
    """
    filter_low_stock = request.GET.get('low_stock') == 'true'
    filter_has_stock = request.GET.get('has_stock') == 'true'
    filter_type = request.GET.get('type', '') 
    
    current_date = timezone.now()
    today_start = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = current_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    thirty_days_ago = current_date - timedelta(days=30)
    week_start = current_date - timedelta(days=7)
    
    # 1. MATERIALLAR RO'YXATI
    # ✅ related_name='transactions' bo'lgani uchun 'transactions' so'zi ishlatiladi
    base_materials_qs = Material.objects.annotate(
        difference=ExpressionWrapper(
            F('quantity') - F('min_stock_level'),
            output_field=DecimalField(max_digits=15, decimal_places=3)
        ),
        total_value=ExpressionWrapper(
            F('quantity') * F('price_per_unit'),
            output_field=DecimalField(max_digits=15, decimal_places=2)
        ), 
    ).order_by('name') 

    materials = base_materials_qs
    if filter_low_stock:
        materials = materials.filter(quantity__lt=F('min_stock_level'))
    if filter_has_stock:
        materials = materials.filter(quantity__gt=0)
    
    paginator = Paginator(materials, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # 2. KIRIM TRANZAKSIYALARI (Barcode qo'shilgan)
    incoming_transactions_raw = MaterialTransaction.objects.filter(
        transaction_type='IN'
    ).select_related('material').order_by('-timestamp')[:100]
    
    income_materials = []
    for tx in incoming_transactions_raw:
        material = tx.material
        quantity = tx.quantity_change
        unit_price = material.price_per_unit if material else Decimal('0') 
        
        income_materials.append({
            'id': tx.id,
            'date': tx.timestamp,
            'barcode': tx.transaction_barcode,  # 🔴 BARCODE SHU YERDA
            'material': {
                'name': material.name if material else 'Noma\'lum',
                'product_name': material.product_name if material and hasattr(material, 'product_name') else '',
                'unit': material.unit if material else ''
            },
            'quantity': quantity,
            'price': unit_price,
            'total': quantity * unit_price,
            'notes': tx.notes or '',
            'supplier': tx.received_by or ''
        })
    
    # 3. CHIQIM TRANZAKSIYALARI
    outgoing_transactions_raw = MaterialTransaction.objects.filter(
        transaction_type='OUT'
    ).select_related('material').order_by('-timestamp')[:100]

    outcome_materials = []
    for tx in outgoing_transactions_raw:
        material = tx.material
        quantity = abs(tx.quantity_change)
        unit_price = material.price_per_unit if material else Decimal('0') 
        outcome_materials.append({
            'id': tx.id,
            'date': tx.timestamp,
            'barcode': tx.transaction_barcode,
            'material': {
                'name': material.name if material else 'Noma\'lum',
                'unit': material.unit if material else ''
            },
            'quantity_change': tx.quantity_change,
            'unit_price': unit_price,
            'total_value': quantity * unit_price,
            'notes': tx.notes or '',
            'department': tx.received_by or '' 
        })
        
    # 4. TOP MATERIALLAR (Xatolik tuzatilgan qism)
    # ✅ materialtransaction o'rniga transactions ishlatildi
    # views.py 1441-qator atrofini shunday o'zgartiring:

    top_materials_qs = Material.objects.annotate(
        # total_incoming hisobi
        total_incoming=Coalesce(
            Sum('materialtransaction__quantity_change', 
                filter=Q(materialtransaction__transaction_type='IN')), 
            Decimal('0'), 
            output_field=DecimalField(max_digits=15, decimal_places=3)
        ),
        # total_outgoing hisobi
        total_outgoing=Coalesce(
            Sum('materialtransaction__quantity_change', 
                filter=Q(materialtransaction__transaction_type='OUT')), 
            Decimal('0'), 
            output_field=DecimalField(max_digits=15, decimal_places=3)
        ),
        # incoming_value hisobi
        incoming_value=ExpressionWrapper(
            Coalesce(
                Sum('materialtransaction__quantity_change', 
                    filter=Q(materialtransaction__transaction_type='IN')), 
                Decimal('0')
            ) * F('price_per_unit'),
            output_field=DecimalField(max_digits=15, decimal_places=2) 
        ),
        # outgoing_value hisobi
        outgoing_value=ExpressionWrapper(
            Coalesce(
                Sum('materialtransaction__quantity_change', 
                    filter=Q(materialtransaction__transaction_type='OUT')), 
                Decimal('0')
            ) * F('price_per_unit'),
            output_field=DecimalField(max_digits=15, decimal_places=2) 
        )
    )
    
    top_incoming_materials = top_materials_qs.filter(total_incoming__gt=0).order_by('-total_incoming')[:10]
    top_outgoing_materials = top_materials_qs.filter(total_outgoing__gt=0).order_by('-total_outgoing')[:10]
    
    context = {
        'materials': page_obj,
        'page_obj': page_obj,
        'income_materials': income_materials,
        'outcome_materials': outcome_materials,
        'top_incoming_materials': top_incoming_materials,
        'top_outgoing_materials': top_outgoing_materials,
        'current_date': current_date,
        'title': 'Omborxona Boshqaruvi',
    }
    
    return render(request, 'orders/material_list.html', context)
# orders/views.py

from django.shortcuts import render
# from .models import Material # Modellar ham import qilingan bo'lishi kerak

# ... (Boshqa view funksiyalaringiz)

# orders/views.py

from django.shortcuts import render
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from .models import Material, MaterialTransaction # Modellar shu yerda import qilinishi kerak

def warehouse_dashboard_view(request):
    """
    Omborxona boshqaruv panelini ko'rsatuvchi funksiya.
    Kerakli statistikalar va tezkor harakatlarni hisoblaydi.
    """
    
    # --- 1. Umumiy Statistikalar ---
    total_material_count = Material.objects.count()

    # --- 2. Kam Zaxira ---
    # current_stock, min_stock_level dan kichik bo'lgan materiallar
    low_stock_materials = Material.objects.filter(
        current_stock__lte=models.F('min_stock_level') # models.F ni ham import qilish kerak
    ).order_by('-current_stock')
    
    low_stock_materials_count = low_stock_materials.count()

    # --- 3. Vaqtga asoslangan Harakatlar Statistikasi (30 kun) ---
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    
    monthly_transactions = MaterialTransaction.objects.filter(
        created_at__gte=thirty_days_ago
    )
    
    # Kirim va Chiqimni hisoblash (umumiy miqdorda)
    monthly_incoming_sum = monthly_transactions.filter(transaction_type='IN').aggregate(Sum('quantity'))['quantity__sum'] or 0
    monthly_outgoing_sum = monthly_transactions.filter(transaction_type='OUT').aggregate(Sum('quantity'))['quantity__sum'] or 0

    monthly_stats = {
        'total_incoming': monthly_incoming_sum,
        'total_outgoing': monthly_outgoing_sum,
    }
    
    # --- 4. So'nggi Harakatlar (Dashboard uchun) ---
    recent_transactions = MaterialTransaction.objects.select_related('material').order_by('-created_at')[:5]

    context = {
        'title': 'Omborxona Boshqaruv Paneli',
        'total_material_count': total_material_count,
        'low_stock_materials_count': low_stock_materials_count,
        'low_stock_materials': low_stock_materials,
        'monthly_stats': monthly_stats,
        'recent_transactions': recent_transactions,
    }
    
    return render(request, 'orders/dashboard.html', context)
@login_required
def material_transaction_detail(request, pk):
    """Material tranzaksiyasi tafsilotlari."""
    transaction = get_object_or_404(MaterialTransaction.objects.select_related(
        'material', 'order', 'performed_by'
    ), pk=pk)
    
    context = {
        'transaction': transaction,
    }
    
    return render(request, 'orders/material_transaction_detail.html', context)
# orders/views.py

from django.shortcuts import render
# ... (boshqa importlar)

def transaction_history_view(request):
    """
    Omborxona harakatlari (kirim/chiqim) tarixini ko'rsatadi.
    """
    # Bu yerda MaterialTransaction modelidan ma'lumotlarni olish logikasi bo'lishi mumkin
    # Masalan: transactions = MaterialTransaction.objects.all().order_by('-timestamp')
    
    context = {
        'title': 'Omborxona Harakatlari Tarixi',
        # 'transactions': transactions,
    }
    return render(request, 'orders/transaction_history.html', context)


# orders/views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def fast_scanner_view(request):
    """
    Tezkor Skanerlash uchun alohida sahifani render qiladi.
    Bu sahifada faqat Kirim/Chiqim rejimi va Skanerlash maydoni bo'ladi.
    """
    context = {
        'title': 'Tezkor Skanerlash Markazi',
    }
    # orders/fast_scanner.html shablonini chaqirish
    return render(request, 'orders/fast_scanner.html', context)


# views.py ga qo'shing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

# orders/views.py
from orders.models import Material
from django.http import JsonResponse
from django.db import transaction as db_transaction
from django.contrib.auth.decorators import login_required

@login_required
def find_material_by_code_api(request):
    if request.method == 'GET':
        code = request.GET.get('code', '').strip()
        
        if not code:
            return JsonResponse({'success': False, 'error': 'Kod kiritilmadi.'}, status=400)
        
        try:
            # 1. Materialni topishga urinish (product_name orqali)
            material = Material.objects.get(product_name__iexact=code)
            is_new = False
            
        except Material.DoesNotExist:
            # 2. Agar topilmasa, uni avtomatik yaratish!
            try:
                with db_transaction.atomic():
                    material = Material.objects.create(
                        name=f"Yangi Material (Kod: {code})",
                        product_name=code, # Kodni bu yerga saqlash
                        unit='dona',
                        quantity=0, # Boshlang'ich qoldiq
                        price_per_unit=0
                        # Agar modelda boshqa majburiy maydonlar bo'lsa, ularni qo'shing (masalan, category_id)
                    )
                is_new = True
            except Exception as create_error:
                return JsonResponse({
                    'success': False, 
                    'error': f"Avtomatik yaratishda xato: {create_error}"
                }, status=500)
        
        # 3. Natijani qaytarish
        return JsonResponse({
            'success': True,
            'material_id': material.id,
            'material_name': material.name,
            'material_code': material.product_name, # Kod sifatida product_name ni yuborish
            'material_unit': material.unit,
            'scanned_raw_code': code, # <-- Shu yerda code o'zgaruvchisi yuborilmoqda
            # ... boshqa maydonlar
            'is_new': is_new
        })
        
    return JsonResponse({'success': False, 'error': 'Faqat GET so\'rovi qabul qilinadi.'}, status=405)

@login_required
@csrf_exempt  # Faqat test uchun
def save_scanned_transactions_api(request):
    """API: Skanerlangan tranzaksiyalarni saqlash"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            
            # Bu yerda ma'lumotlarni saqlash logikasi
            # Misol:
            # for item in data['items']:
            #     Transaction.objects.create(...)
            
            return JsonResponse({
                'success': True,
                'message': f"{len(data.get('items', []))} ta element saqlandi"
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
# orders/views.py

from django.shortcuts import render, redirect, get_object_or_404
from .forms import MaterialTransactionForm # Forma mavjudligini taxmin qilamiz
# ... (boshqa importlar)

def add_transaction_view(request):
    """
    Yangi omborxona harakatini (kirim yoki chiqim) qo'shish.
    """
    if request.method == 'POST':
        form = MaterialTransactionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('material_list') # Muvaffaqiyatli saqlangandan keyin inventarizatsiya sahifasiga qaytish
    else:
        form = MaterialTransactionForm()
        
    context = {
        'title': 'Yangi Harakat Qo\'shish (Kirim/Chiqim)',
        'form': form
    }
    return render(request, 'orders/add_transaction.html', context)



# orders/views.py

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from .models import Material, MaterialTransaction
from django.shortcuts import get_object_or_404



@require_POST
def remove_transaction_view(request):
    """
    Omborxona materialini chiqim qilish (omborxona zaxirasidan olib tashlash)
    """
    if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid Request'}, status=400)
    
    try:
        material_id = request.POST.get('material_id')
        quantity = float(request.POST.get('quantity'))
        reason = request.POST.get('reason', 'Chiqim sababi ko\'rsatilmadi')
        
        material = get_object_or_404(Material, pk=material_id)
        
        if quantity <= 0:
            return JsonResponse({'success': False, 'error': 'Noto\'g\'ri miqdor kiritildi'}, status=400)
        
        with transaction.atomic():
            # Zaxira yetarli yoki yo'qligini tekshirish
            if material.current_stock < quantity:
                return JsonResponse({'success': False, 'error': f'Zaxirada yetarli {material.unit} mavjud emas. (Mavjud: {material.current_stock})'}, status=400)
            
            # 1. Zaxirani yangilash
            material.current_stock -= quantity
            material.save()
            
            # 2. Tranzaksiyani yaratish (Chiqim)
            MaterialTransaction.objects.create(
                material=material,
                transaction_type='OUT', # Chiqim
                quantity=quantity,
                unit=material.unit,
                reason=reason,
                # user=request.user # Agar foydalanuvchi tizimga kirgan bo'lsa
            )
        
        return JsonResponse({'success': True, 'message': 'Chiqim muvaffaqiyatli amalga oshirildi.'})
        
    except Material.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Material topilmadi.'}, status=404)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Miqdor noto\'g\'ri formatda.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Kutilmagan xato: {str(e)}'}, status=500)
    


@login_required
def material_transaction_delete(request, pk):
    """Material tranzaksiyasini o'chirish."""
    transaction = get_object_or_404(MaterialTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            # Qaytarish logikasi (agar kerak bo'lsa)
            material = transaction.material
            if transaction.transaction_type == 'IN':
                material.quantity -= transaction.quantity_change
            else:  # OUT
                material.quantity += transaction.quantity_change
            
            material.save()
            transaction.delete()
            
            messages.success(request, "✅ Tranzaksiya muvaffaqiyatli o'chirildi.")
            return redirect('material_transaction_list')
            
        except Exception as e:
            messages.error(request, f"❌ Xatolik: {str(e)}")
    
    context = {
        'transaction': transaction,
    }
    
    return render(request, 'orders/material_transaction_confirm_delete.html', context)
def get_material_data():
    """
    Material ma'lumotlarini JSON uchun tayyorlash
    """
    material_objects = Material.objects.all().select_related('category').values(
        'id', 'name', 'unit', 'quantity', 'category__name'
    )
    
    material_data = {
        str(m['id']): {
            'name': m['name'], 
            'unit': m['unit'], 
            'quantity': float(m['quantity']) if m['quantity'] is not None else 0,
            'category': m['category__name'] if m['category__name'] else 'Kategoriyasiz'
        } 
        for m in material_objects
    }
    
    return material_data


# orders/views.py


from django.db.models.functions import Coalesce # ⬅️ Mana bu qatorni qo'shing
from decimal import Decimal # ✅ Decimal to'g'ri import qilindi
def material_sarfi_report(request):
    
    # Kvadrat maydoni NULL bo'lishi mumkinligini hisobga olamiz
    # Shuningdek, DecimalField bilan ishlash uchun Decimal(0) dan foydalanamiz
    
    # =======================================================================
    # 1. SARFNI HISOBLASH UCHUN KVADRAT METRLARNI GURUH BO'YICHA YIG'ISH
    # =======================================================================
    
    # Barcha buyurtmalarni filtrlash (misol uchun, faqat 'BAJARILDI' statusdagilarni)
    # Agar barcha kiritilgan buyurtmalar kerak bo'lsa, filter() qismini olib tashlang
    all_orders = Order.objects.all() 
    
    # Barcha panellarning umumiy kvadratini topish (Jami List uchun kerak)
    # Coalesce(Sum('panel_kvadrat'), Decimal(0)) yig'indi bo'sh bo'lsa 0 ni qaytaradi
    total_kvadrat = all_orders.aggregate(
        sum_kvadrat=Coalesce(Sum('panel_kvadrat'), Decimal(0))
    )['sum_kvadrat']

    # Qalinlik bo'yicha kvadrat yig'indilarini hisoblash (Siryo uchun kerak)
    sum_kvadrat_5mm = all_orders.filter(panel_thickness='5').aggregate(
        sum_kvadrat=Coalesce(Sum('panel_kvadrat'), Decimal(0))
    )['sum_kvadrat']

    sum_kvadrat_10mm = all_orders.filter(panel_thickness='10').aggregate(
        sum_kvadrat=Coalesce(Sum('panel_kvadrat'), Decimal(0))
    )['sum_kvadrat']

    sum_kvadrat_15mm = all_orders.filter(panel_thickness='15').aggregate(
        sum_kvadrat=Coalesce(Sum('panel_kvadrat'), Decimal(0))
    )['sum_kvadrat']

    # =======================================================================
    # 2. SARF FORMULALARINI QO'LLASH
    # =======================================================================
    
    # 1. Jami List Sarfi (m²): (Total Kvadrat * 2) + 10
    # Natijani Decimal formatda saqlash, floatga o'tkazishdan qochish yaxshi amaliyot
    jami_list_sarfi = (total_kvadrat * Decimal(2)) + Decimal(10)
    
    # 2. Siryo Sarfi (kg): Har bir qalinlik uchun alohida hisoblash
    
    # 5mm siryo: Sum Kvadrat * 2
    siryo_5mm_sarfi = sum_kvadrat_5mm * Decimal(2)
    
    # 10mm siryo: Sum Kvadrat * 4
    siryo_10mm_sarfi = sum_kvadrat_10mm * Decimal(4)
    
    # 15mm siryo: Sum Kvadrat * 6
    siryo_15mm_sarfi = sum_kvadrat_15mm * Decimal(6)

    # Umumiy Siryo Sarfi
    jami_siryo_sarfi = siryo_5mm_sarfi + siryo_10mm_sarfi + siryo_15mm_sarfi

    # =======================================================================
    # 3. CONTEXT GA YUKLASH
    # =======================================================================
    
    context = {
        # Umumiy yakuniy hisobot
        'jami_list_sarfi': jami_list_sarfi,
        'jami_siryo_sarfi': jami_siryo_sarfi,
        
        # Detallashgan siryo hisoboti
        'siryo_5mm_sarfi': siryo_5mm_sarfi,
        'siryo_10mm_sarfi': siryo_10mm_sarfi,
        'siryo_15mm_sarfi': siryo_15mm_sarfi,
        
        # Xom ma'lumotlar
        'total_kvadrat': total_kvadrat,
        'sum_kvadrat_5mm': sum_kvadrat_5mm,
        'sum_kvadrat_10mm': sum_kvadrat_10mm,
        'sum_kvadrat_15mm': sum_kvadrat_15mm,
    }
    
    return render(request, 'orders/material_sarfi_report.html', context)



from decimal import Decimal
@login_required
@user_passes_test(is_report_viewer_or_observer, login_url='/login/')  # ✅ YANGI
def worker_activity_report_view(request): 
    """
    Ustalar ish faoliyati bo'yicha hisobot (Bajarilgan ishlar)
    Sanalar bo'yicha filtrlash imkoniyati mavjud.
    """
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Faqat bajarilgan buyurtmalarni filtrlash (TAYYOR va BAJARILDI statuslari)
    worker_report_orders = Order.objects.filter(
        status__in=['TAYYOR', 'BAJARILDI']
    ).filter(
        worker_finished_at__isnull=False 
    ).prefetch_related(
        'assigned_workers__user'
    ) 
    
    # Sana bo'yicha filtrlash mantig'i
    worker_filter_q = Q()
    if start_date:
        worker_filter_q &= Q(worker_finished_at__gte=start_date)
    if end_date:
        try:
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            worker_filter_q &= Q(worker_finished_at__lt=end_datetime)
        except ValueError:
            messages.error(request, "Noto'g'ri sana formati kiritildi.")
            
    worker_report_orders = worker_report_orders.filter(worker_filter_q)

    # Ustalar bo'yicha guruhlash va statistikani hisoblash
    worker_report_list = worker_report_orders.values(
    'assigned_workers__user__first_name',
    'assigned_workers__user__last_name',
    ).annotate(
        total_finished_kvadrat=Sum('panel_kvadrat'), 
        total_order_count=Count('id')
    ).order_by('-total_finished_kvadrat')
    
    total_finished_kvadrat = worker_report_list.aggregate(Sum('total_finished_kvadrat'))['total_finished_kvadrat__sum'] or 0

    context = {
        "title": "Ustalar Ish Faoliyati Hisoboti",
        'worker_report_list': worker_report_list,
        'total_finished_kvadrat': total_finished_kvadrat,
        'start_date': start_date,
        'end_date': end_date,
        'is_observer': is_observer(request.user),  # ✅ YANGI
    }

    return render(request, 'orders/weekly_report_view.html', context)

@login_required
@user_passes_test(is_report_viewer_or_observer, login_url='/')  # ✅ YANGI
def export_worker_activity_csv(request):
    """
    Ustalarning ish faoliyati hisobotini CSV fayl shaklida eksport qiladi.
    """
    # 1. CSV javobini tayyorlash
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="usta_faoliyat_hisoboti_{datetime.now().strftime("%Y-%m-%d")}.csv"'
    
    writer = csv.writer(response)
    
    # Jadval sarlavhalari
    writer.writerow([
        'T/r', 
        'Usta F.I.Sh.', 
        'Bajarilgan Kvadratura (m²)', 
        'Bajarilgan Buyurtmalar Soni'
    ])

    # 2. Filtrlash shartlarini yaratish
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # ✅ Xato tuzatildi: Statusni to'g'ri string qiymati bilan filtrlash
    worker_filter_q = Q(status='FINISHED') 
    
    start_date = None
    end_date = None

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            worker_filter_q &= Q(updated_at__date__gte=start_date)
        except ValueError:
            pass 

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            worker_filter_q &= Q(updated_at__date__lte=end_date)
        except ValueError:
            pass

    # 3. Hisobot ma'lumotlarini olish
    worker_report_list = Order.objects.filter(worker_filter_q).exclude(assigned_workers__isnull=True).values(
        'assigned_workers__user__first_name',
        'assigned_workers__user__last_name'
    ).annotate(
    total_finished_kvadrat=Sum('panel_kvadrat', default=0), 
    total_order_count=Count('id')

    ).order_by('assigned_workers__user__first_name')
    
    # 4. CSV ga ma'lumotlarni yozish
    for i, worker in enumerate(worker_report_list):
        writer.writerow([
            i + 1,
            f"{worker['assigned_workers__user__first_name']} {worker['assigned_workers__user__last_name']}",
            f"{worker['total_finished_kvadrat']:.2f}",
            worker['total_order_count']
        ])
        
    return response

@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def export_orders_csv(request):
    """Buyurtmalarni CSV formatida eksport qilish (oxirgi 7 kunlik)."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="EcoProm_Buyurtmalar_Hisboti_7kunlik.csv"'

    writer = csv.writer(response, delimiter=';') 

    writer.writerow([
        "Buyurtma Raqami", 
        "Xaridor Nomi", 
        "Kvadrat (m²)", 
        "Summa (so'm)", 
        "Status", 
        "Kiritilgan Sana",
        "Kiritgan Xodim"
    ])

    seven_days_ago = date.today() - timedelta(days=7)
    orders = Order.objects.filter(
        created_at__gte=seven_days_ago
    ).order_by('-created_at')

    for order in orders:
        writer.writerow([
            order.order_number,
            order.customer_name,
            order.panel_kvadrat,
            order.total_price,
            order.get_status_display(),
            order.created_at.strftime("%Y-%m-%d %H:%M"),
            order.created_by.get_full_name() if order.created_by else "Noma'lum", 
        ])

    return response

@login_required
@user_passes_test(is_report_viewer_or_observer, login_url='/login/')
def sales_report_view(request):
    """Vaqt oralig'i bo'yicha sotuv hisobotini ko'rsatish va filtrlash."""
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    today = date.today()
    
    try:
        if start_date_str and end_date_str:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        else:
            start_date = today - timedelta(days=30)
            end_date = today
    except ValueError:
        messages.error(request, "Noto'g'ri sana formati kiritildi. Iltimos, YYYY-MM-DD formatida kiriting.")
        start_date = today - timedelta(days=30)
        end_date = today

    # 🔴 Asosiy buyurtmalar
    main_orders = Order.objects.filter(
        parent_order__isnull=True,  # Faqat asosiy buyurtmalar
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).order_by('-created_at')

    # 🔴 Child buyurtmalar (alohida)
    child_orders = Order.objects.filter(
        parent_order__isnull=False,  # Faqat child buyurtmalar
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).order_by('-created_at')

    # 🔴 Barcha buyurtmalar (umumiy ko'rish uchun)
    all_orders = Order.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).order_by('-created_at')

    total_orders_count = main_orders.count()
    total_square = main_orders.aggregate(Sum('panel_kvadrat'))['panel_kvadrat__sum'] or 0
    total_revenue = main_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0

    context = {
        "title": "Sotuv Hisoboti (Vaqt Oralig'i)",
        'report_orders': main_orders,  # 🔴 Faqat asosiylar ko'rsatiladi
        'child_orders': child_orders,  # 🔴 Child buyurtmalar (alohida)
        'all_orders': all_orders,  # 🔴 Barcha buyurtmalar
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'total_orders_count': total_orders_count,
        'total_square': total_square,
        'total_revenue': total_revenue,
        'is_glavniy_admin': True,
        'today': timezone.now().date(),
        'is_observer': is_observer(request.user),
    }
    return render(request, 'orders/sales_report.html', context)



@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def product_audit_log_view(request):
    """Mahsulot/Buyurtma o'zgarishlari jurnalini ko'rish funksiyasi."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    try:
        order_content_type = ContentType.objects.get(app_label='orders', model='order')
        
        log_entries = LogEntry.objects.filter(
            content_type=order_content_type
        ).select_related('user').order_by('-action_time')
        
        for log in log_entries:
            try:
                log.related_object_name = Order.objects.get(pk=log.object_id).order_number
            except Order.DoesNotExist:
                log.related_object_name = log.object_repr
    except ContentType.DoesNotExist:
        log_entries = []
        messages.error(request, "Buyurtma (Order) modeli uchun ContentType topilmadi. `LogEntry` filtrlanmaydi.")
    

    context = {
        "title": "Mahsulot O'zgarishlari Jurnali (Audit Log)",
        'log_entries': log_entries,
        'is_glavniy_admin': True,
        'is_observer': False, 
    }
    
    return render(request, 'orders/product_audit_log.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def export_audit_log_csv(request):
    """Audit Log yozuvlarini CSV formatida eksport qilish."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="EcoProm_Audit_Log_Hisoboti.csv"'

    writer = csv.writer(response, delimiter=';') 

    writer.writerow([
        "Harakat Vaqti", 
        "Foydalanuvchi", 
        "Harakat Turi", 
        "Buyurtma Raqami/Obyekt", 
        "O'zgarish Tafsiloti (Change Message)"
    ])

    try:
        order_content_type = ContentType.objects.get(app_label='orders', model='order')
        log_entries = LogEntry.objects.filter(
            content_type=order_content_type
        ).select_related('user').order_by('-action_time')
    except ContentType.DoesNotExist:
        messages.error(request, "Buyurtma (Order) modeli ContentType topilmadi. Eksport qilish bekor qilindi.")
        return redirect('product_audit_log_view') 

    def get_action_type(flag):
        if flag == ADDITION:
            return 'Yaratildi (ADDITION)'
        elif flag == CHANGE:
            return 'Tahrirlandi (CHANGE)'
        elif flag == DELETION:
            return 'Oʻchirildi (DELETION)'
        return 'Nomaʼlum'

    for log in log_entries:
        
        object_identifier = ''
        try:
            object_identifier = Order.objects.get(pk=log.object_id).order_number
        except Order.DoesNotExist:
            object_identifier = f"O'chirilgan obyekti (ID: {log.object_id})"

        
        writer.writerow([
            log.action_time.strftime("%Y-%m-%d %H:%M:%S"),
            log.user.get_full_name() or log.user.username,
            get_action_type(log.action_flag),
            object_identifier,
            log.change_message.replace('\r\n', ' ').replace('\n', ' ') 
        ])

    return response
