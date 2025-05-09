import json
import re

def parse_api_response(response):
    """
    API yanıtlarını güvenli bir şekilde ayrıştıran yardımcı fonksiyon.
    HTML yanıtlarını işlerken oluşabilecek JSON hatalarını önler.
    
    Args:
        response: API'den gelen yanıt (response objesi veya metin)
        
    Returns:
        dict: Ayrıştırılmış JSON yanıtı veya hata durumunda uygun hata mesajı içeren sözlük
    """
    try:
        # Eğer response bir response objesi ise, önce text() metodunu çağır
        if hasattr(response, 'text'):
            content = response.text
        else:
            content = response
            
        # HTML içeriği kontrolü
        if content.strip().startswith('<!DOCTYPE') or content.strip().startswith('<html'):
            return {
                'success': False,
                'error': 'Sunucu HTML yanıtı döndürdü. Oturum süresi dolmuş veya bir sunucu hatası oluşmuş olabilir.'
            }
            
        # JSON ayrıştırma
        return json.loads(content)
    except json.JSONDecodeError as e:
        # JSON ayrıştırma hatası durumunda
        return {
            'success': False,
            'error': f'JSON ayrıştırma hatası: {str(e)}. Sunucu geçersiz bir yanıt döndürdü.'
        }
    except Exception as e:
        # Diğer hatalar
        return {
            'success': False,
            'error': f'Bir hata oluştu: {str(e)}'
        }