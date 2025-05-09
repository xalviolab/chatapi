# RAG Sistemine Uygun OpenRouter Modelleri

## Mevcut Durum Analizi

Projenizde RAG (Retrieval Augmented Generation) sistemi başarıyla kurulmuş ve PDF'lerden veri çıkarma işlemi yapılmıştır. Ancak frontend'de RAG durum göstergeleri doğru şekilde çalışmasına rağmen, kullanıcı sorgularında RAG sisteminin arama yaptığına dair bildirimler görünmüyor. Bu durum, mevcut modelin RAG sistemiyle tam uyumlu olmadığını göstermektedir.

Mevcut sistemde DeepSeek Chat modeli kullanılmaktadır:
```
<option value="deepseek/deepseek-chat-v3-0324:free">DeepSeek Chat</option>
```

## RAG Sistemine Uygun OpenRouter Modelleri

Aşağıda OpenRouter'da ücretsiz veya düşük maliyetli olarak kullanılabilen ve RAG sistemleri için uygun olan modeller listelenmiştir. Bu modeller, büyük bağlam pencereleri ve bilgi alımı yetenekleriyle RAG sistemleri için idealdir.

### Ücretsiz veya Düşük Maliyetli Modeller

1. **Mistral AI Modelleri**
   - **Mistral Large**
     - Bağlam Penceresi: 32K token
     - Giriş/Çıkış Maliyeti: $2/$6 (1M token)
     - Özellikler: Mükemmel bilgi alımı, RAG sistemleri için optimize edilmiş
     - Model ID: `mistralai/mistral-large`

   - **Mistral Medium**
     - Bağlam Penceresi: 32K token
     - Giriş/Çıkış Maliyeti: $0.9/$2.7 (1M token)
     - Özellikler: İyi bilgi alımı, orta seviye maliyet
     - Model ID: `mistralai/mistral-medium`

   - **Mistral Small**
     - Bağlam Penceresi: 32K token
     - Giriş/Çıkış Maliyeti: $0.2/$0.6 (1M token)
     - Özellikler: Uygun fiyatlı, RAG için yeterli performans
     - Model ID: `mistralai/mistral-small`

2. **Llama Tabanlı Modeller**
   - **Nous Hermes 3 (Llama 3.1 405B)**
     - Bağlam Penceresi: 131K token
     - Giriş/Çıkış Maliyeti: $0.9/$0.9 (1M token)
     - Özellikler: Çok geniş bağlam penceresi, RAG için ideal
     - Model ID: `nousresearch/hermes-3-llama-3.1-405b`

   - **Meta Llama 3 70B**
     - Bağlam Penceresi: 8K token
     - Giriş/Çıkış Maliyeti: $0.9/$0.9 (1M token)
     - Özellikler: Güçlü bilgi işleme, açık kaynak
     - Model ID: `meta-llama/llama-3-70b-instruct`

3. **Claude Modelleri**
   - **Claude 3 Haiku**
     - Bağlam Penceresi: 200K token
     - Giriş/Çıkış Maliyeti: $0.25/$1.25 (1M token)
     - Özellikler: Çok geniş bağlam penceresi, hızlı yanıt süresi
     - Model ID: `anthropic/claude-3-haiku`

   - **Claude 3 Sonnet**
     - Bağlam Penceresi: 200K token
     - Giriş/Çıkış Maliyeti: $3/$15 (1M token)
     - Özellikler: Mükemmel bilgi alımı, çok geniş bağlam penceresi
     - Model ID: `anthropic/claude-3-sonnet`

4. **Diğer Uygun Modeller**
   - **NVIDIA Nemotron Ultra (Llama 3.1 253B)**
     - Bağlam Penceresi: 128K token
     - Giriş/Çıkış Maliyeti: Ücretsiz (OpenRouter üzerinden)
     - Özellikler: 235 milyar parametre ile eğitilmiş, çok geniş bağlam penceresi, üstün bilgi işleme
     - Model ID: `nvidia/llama-3.1-nemotron-ultra-253b-v1:free`

   - **WizardLM-2 8x22B**
     - Bağlam Penceresi: 66K token
     - Giriş/Çıkış Maliyeti: $0.62/$0.62 (1M token)
     - Özellikler: Geniş bağlam penceresi, iyi bilgi işleme
     - Model ID: `microsoft/wizardlm-2-8x22b`

## Öneriler

1. **En Uygun Maliyet/Performans Oranı İçin**:
   - `mistralai/mistral-small` - Düşük maliyet, yeterli bağlam penceresi ve RAG için uygun performans

2. **En İyi Performans İçin**:
   - `nvidia/llama-3.1-nemotron-ultra-253b-v1:free` - 235 milyar parametre ile eğitilmiş, çok geniş bağlam penceresi ve ücretsiz erişim
   - `anthropic/claude-3-haiku` - Çok geniş bağlam penceresi ve makul maliyet
   - `nousresearch/hermes-3-llama-3.1-405b` - Geniş bağlam penceresi ve dengeli maliyet

3. **Mevcut Modeli Değiştirmek İçin**:
   ```html
   <select id="model-select">
       <option value="meta-llama/llama-4-maverick:free">Llama 4 Maverick</option>
       <option value="nvidia/llama-3.1-nemotron-ultra-253b-v1:free">NVIDIA Nemotron Ultra</option>
       <option value="mistralai/mistral-small">Mistral Small</option>
       <option value="anthropic/claude-3-haiku">Claude 3 Haiku</option>
       <option value="nousresearch/hermes-3-llama-3.1-405b">Hermes 3 (Llama 3.1)</option>
   </select>
   ```

## Sonuç

RAG sisteminiz artık Meta'nın Llama 4 Maverick modelini kullanmaktadır. Bu model, geniş bağlam penceresi ve ücretsiz erişim imkanı ile RAG sistemleri için uygun bir seçenektir. Ayrıca NVIDIA Nemotron Ultra modeli de alternatif olarak sunulmaktadır. Bu model, 235 milyar parametre ile eğitilmiş olması ve geniş bağlam penceresi ile RAG sistemleri için mükemmel bir seçenektir. İsterseniz Mistral Small veya Claude 3 Haiku gibi modelleri de ekleyerek kullanıcılara farklı model seçenekleri sunabilirsiniz. Bu modeller, RAG sisteminin doğru şekilde çalışmasını ve kullanıcılara daha doğru ve kapsamlı yanıtlar vermesini sağlayacaktır.