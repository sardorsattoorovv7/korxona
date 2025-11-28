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
    is_observer = is_in_group(request.user, 'Kuzatuvchi')  # ✅ YANGI

    # Boshlang'ich Buyurtmalar
    orders = Order.objects.all().order_by('-created_at')
    
    # Filterlash mantigi
    should_filter = True 

    if is_glavniy_admin or is_production_boss or is_manager_or_confirmer or is_observer:  # ✅ YANGI
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
                
                if not orders.exists():
                    messages.info(request, "Sizga tayinlangan buyurtmalar topilmadi.")

            except Exception:
                orders = orders.none() 
                messages.warning(request, "Buyurtmalarni yuklashda xato: Usta profili noto'g'ri bog'langan bo'lishi mumkin.")
            
            should_filter = True

    if should_filter and not is_worker:
        pass

    # Muddat buzilishini tekshirish
    if is_glavniy_admin or is_production_boss:
        overdue_orders = orders.filter(
            deadline__lt=timezone.now(),
            status__in=['TASDIQLANDI', 'USTA_QABUL_QILDI', 'USTA_BOSHLA', 'ISHDA', 'KIRITILDI']
        )
        for order in overdue_orders:
            check_and_create_overdue_alerts(order)

    user_notifications = Notification.objects.filter(user=request.user, is_read=False)[:5]
    
    context = {
        'orders': orders,
        'is_glavniy_admin': is_glavniy_admin,
        'is_manager': is_manager_or_confirmer, 
        'is_production_boss': is_production_boss,
        'is_worker': is_worker,
        'is_observer': is_observer,  # ✅ YANGI
        'notifications': user_notifications, 
        'now': timezone.now(), 
    }
    return render(request, 'orders/order_list.html', context)

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
    """Usta ishni yakunlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)

    if not request.user.is_superuser and not order.assigned_workers.filter(user=request.user).exists():
        messages.error(request, "Siz bu operatsiyani bajarishga ruxsat etilmagansiz.")
        return redirect('order_list')

    if not order.finish_image:
         messages.error(request, "Ishni tugatishdan oldin, yakuniy rasm (**Tugatish Rasmi**) yuklashingiz kerak.")
         return redirect('order_detail', pk=order.pk)
        
    if order.status in ['USTA_BOSHLA', 'ISHDA']: 
        current_time = timezone.now()
        order.status = 'USTA_TUGATDI'
        order.worker_finished_at = current_time 
        
        if order.deadline and current_time > order.deadline:
            check_and_create_overdue_alerts(order)
            messages.warning(request, f"⚠️ Buyurtma #{order.order_number} muddatidan kech yakunlandi.")
            
        order.save(update_fields=['status', 'worker_finished_at'])
        messages.success(request, f"Buyurtma #{order.order_number} usta tomonidan yakunlandi. Status: USTA YAKUNLADI.")
    else:
        messages.warning(request, f"Ishni yakunlash uchun buyurtma 'Usta Boshladi' yoki 'Ishda' statusida bo'lishi kerak.")
        
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
            
            order.save()
            form.save_m2m() 
            
            LogEntry.objects.log_action(
                user_id=request.user.id,
                content_type_id=ContentType.objects.get_for_model(order).pk,
                object_id=order.pk,
                object_repr=str(order),
                action_flag=ADDITION,
                change_message=f"Yangi buyurtma kiritildi: №{order.order_number}"
            )

            messages.success(request, f"Buyurtma №{order.order_number} muvaffaqiyatli kiritildi. Ustalar tayinlandi.")
            
            try:
                manager_group = Group.objects.get(name='Menejer/Tasdiqlovchi') 
                for manager in manager_group.user_set.all():
                    Notification.objects.create(
                        user=manager,
                        order=order,
                        message=f"Yangi buyurtma kiritildi: №{order.order_number}. Tasdiqlash talab qilinadi."
                    )
            except Group.DoesNotExist:
                messages.warning(request, "Menejer/Tasdiqlovchi guruhi topilmadi.")

            if order.assigned_workers.exists():
                for worker in order.assigned_workers.all():
                    Notification.objects.create(
                        user=worker.user,
                        order=order,
                        message=f"Buyurtma №{order.order_number} sizga tayinlandi. Tasdiqlanishini kuting."
                    )
            
            return redirect('order_list')
    else:
        form = OrderForm()
    
    return render(request, 'orders/order_create.html', {'form': form})

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
        
        LogEntry.objects.log_action(
            user_id=request.user.id,
            content_type_id=ContentType.objects.get_for_model(order).pk,
            object_id=order.pk,
            object_repr=str(order),
            action_flag=CHANGE,
            change_message=f"Status o'zgartirildi: {order.get_status_display()} -> TAYYOR"
        )
        
        messages.success(request, f"Buyurtma №{order.order_number} **Tayyor** deb belgilandi. Jarayon yakunlandi.")
        
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
def order_edit(request, pk):
    """Buyurtmani Glavniy Admin tomonidan tahrirlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
    order = get_object_or_404(Order, pk=pk)
    original_order = get_object_or_404(Order, pk=pk)
    
    if request.method == 'POST':
        form = OrderForm(request.POST, request.FILES, instance=order)
        if form.is_valid():
            
            changed_fields = []
            
            fields_to_check = {
                'order_number': 'Buyurtma Raqami',
                'customer_name': 'Xaridor Nomi',
                'panel_kvadrat': "Kvadrat (m²)",
                'total_price': "Summa (so'm)",
                'deadline': "Muddat",
            }
            
            for field_name, verbose_name in fields_to_check.items():
                old_value = getattr(original_order, field_name)
                new_value = form.cleaned_data.get(field_name)
                
                if str(old_value) != str(new_value):
                    changed_fields.append(f"{verbose_name}: '{old_value}' -> '{new_value}'")

            if 'assigned_workers' in form.cleaned_data:
                old_workers = list(original_order.assigned_workers.all().values_list('user__username', flat=True))
                new_workers = list(form.cleaned_data['assigned_workers'].values_list('user__username', flat=True))
                
                if set(old_workers) != set(new_workers):
                    old_str = ", ".join(old_workers) or 'Hech kim'
                    new_str = ", ".join(new_workers) or 'Hech kim'
                    changed_fields.append(f"Tayinlangan Ustalar: '{old_str}' -> '{new_str}'")

            order = form.save(commit=False)
            
            if 'deadline' in form.changed_data and order.deadline and order.deadline > timezone.now():
                 if hasattr(order, 'deadline_breach_alert_sent') and order.deadline_breach_alert_sent:
                    order.deadline_breach_alert_sent = False 
                    
            order.save()
            form.save_m2m() 
            
            if changed_fields:
                change_message = "Buyurtma tahrirlandi. O'zgarishlar: " + "; ".join(changed_fields)
            else:
                change_message = "Buyurtma tahrirlandi, lekin asosiy ma'lumotlarda o'zgarish yo'q."
            
            LogEntry.objects.log_action(
                user_id=request.user.id,
                content_type_id=ContentType.objects.get_for_model(order).pk,
                object_id=order.pk,
                object_repr=str(order),
                action_flag=CHANGE,
                change_message=change_message
            )
            
            messages.success(request, f"Buyurtma №{order.order_number} muvaffaqiyatli tahrirlandi.")
            return redirect('order_list')
    else:
        form = OrderForm(instance=order)
    
    context = {
        'form': form,
        'order': order,
        'is_edit': True,
    }
    return render(request, 'orders/order_create.html', context)

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

@login_required
@user_passes_test(is_report_viewer_or_observer, login_url='/login/')  # ✅ YANGI
def weekly_report_view(request):
    """
    Buyurtmalar va Ustalar ish faoliyati bo'yicha umumiy hisobot.
    Sanalar bo'yicha filtrlash imkoniyati mavjud.
    """
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Umumiy Buyurtmalar (Barcha statusdagilar)
    orders = Order.objects.all().select_related('created_by')
    
    # Umumiy hisobotni filtrlash uchun Q obyektini yaratamiz
    filter_q = Q()
    
    # Sana filtrlash logikasi (Kiritilgan sanaga asoslanamiz, lekin usta hisoboti uchun pastda alohida ishlaymiz)
    if start_date:
        filter_q &= Q(created_at__gte=start_date)
    if end_date:
        # Tugash kuniga 1 kun qo'shamiz, chunki date__lte faqat 00:00:00 ni oladi
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        filter_q &= Q(created_at__lt=end_datetime)
        
    report_orders = orders.filter(filter_q).order_by('-created_at')

    # 1. Umumiy Statistikani hisoblash (Buyurtmalar Ro'yxati asosida)
    total_orders_count = report_orders.count()
    total_square = report_orders.aggregate(Sum('panel_kvadrat'))['panel_kvadrat__sum'] or 0
    total_revenue = report_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    
    # ========================================================
    # 2. 💡 YENGI LOGIKA: Ustalar Ish Faoliyati Hisoboti
    # ========================================================
    
    # Faqat bajarilgan buyurtmalarni filtrlash (TAYYOR va BAJARILDI statuslari)
    worker_report_orders = Order.objects.filter(
        status__in=['TAYYOR', 'BAJARILDI']  # Ikkala statusni ham qo'shdik
    ).filter(
        # Usta ishni tugatgan vaqti bo'yicha filtrlash
        worker_finished_at__isnull=False 
    ).select_related(
        # Ustaning nomini chiqarish uchun kerak
    ).prefetch_related(
        'assigned_workers__user' # Workers orqali User ma'lumotlarini yuklaymiz
    ) 
    
    # Agar sana filtrlari qo'yilgan bo'lsa, uni qo'llash
    worker_filter_q = Q()
    if start_date:
        worker_filter_q &= Q(worker_finished_at__gte=start_date)
    if end_date:
        # Tugash kuniga 1 kun qo'shamiz (Yuqoridagi kabi)
        end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        worker_filter_q &= Q(worker_finished_at__lt=end_datetime)
        
    worker_report_orders = worker_report_orders.filter(worker_filter_q)

    # Ustalar bo'yicha guruhlash va hisoblash
    worker_summary = {}
    for order in worker_report_orders:
        for worker in order.assigned_workers.all():
            worker_key = worker.user.get_full_name() or worker.user.username
            
            if worker_key not in worker_summary:
                worker_summary[worker_key] = {
                    'total_kvadrat': 0.0,
                    'total_orders': 0,
                    'role': worker.get_role_display() 
                }
            
            # Kvadratni qo'shish (Bitta buyurtma bir nechta ustaga taqsimlangan bo'lsa,
            # har bir ustaga to'liq kvadratni hisoblaymiz. Agar siz uni taqsimlashni 
            # istasangiz, qo'shimcha mantiq kerak, lekin odatda hisobotda shunday qilinadi).
            worker_summary[worker_key]['total_kvadrat'] += order.panel_kvadrat
            worker_summary[worker_key]['total_orders'] += 1

    # Hisobotni ro'yxatga aylantirish (templategacha oson o'tishi uchun)
    worker_report_list = sorted(
        [{'worker_name': k, **v} for k, v in worker_summary.items()],
        key=lambda x: x['total_kvadrat'],
        reverse=True
    )
    
    # Umumiy bajarilgan kvadratura
    total_finished_kvadrat = sum(item['total_kvadrat'] for item in worker_report_list)
    # ========================================================
    # 2. 💡 YENGI LOGIKA TUGADI
    # ========================================================

    context = {
        # Umumiy hisobot konteksti
        'report_orders': report_orders,
        'total_orders_count': total_orders_count,
        'total_square': total_square,
        'total_revenue': total_revenue,
        'start_date': start_date,
        'end_date': end_date,
        
        # 💡 YANGI: Ustalar hisoboti konteksti
        'worker_report_list': worker_report_list,
        'total_finished_kvadrat': total_finished_kvadrat,
        
        # ✅ YANGI: Role konteksti
        'is_observer': is_observer(request.user),
    }

    return render(request, 'orders/weekly_report_view.html', context)

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
@user_passes_test(lambda u: u.is_superuser or is_in_group(u, 'Glavniy Admin'), login_url='/login/')
def sales_report_view(request):
    """Vaqt oralig'i bo'yicha sotuv hisobotini ko'rsatish va filtrlash."""
    # Kuzatuvchi tekshiruvi
    if is_observer(request.user):
        messages.error(request, "Kuzatuvchi rejimida bu amalni bajarish mumkin emas.")
        return redirect('order_list')
        
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

    report_orders = Order.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
    ).order_by('-created_at')

    total_orders_count = report_orders.count()
    total_square = report_orders.aggregate(Sum('panel_kvadrat'))['panel_kvadrat__sum'] or 0
    total_revenue = report_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0

    context = {
        "title": "Sotuv Hisoboti (Vaqt Oralig'i)",
        'report_orders': report_orders,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'total_orders_count': total_orders_count,
        'total_square': total_square,
        'total_revenue': total_revenue,
        'is_glavniy_admin': True,
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
