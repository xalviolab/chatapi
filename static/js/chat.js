document.addEventListener('DOMContentLoaded', function () {
    const socket = io();
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const chatMessages = document.getElementById('chat-messages');
    const modelSelect = document.getElementById('model-select');

    let currentChatId = null;
    let isWaitingForResponse = false;
    let responseTimeout = null;
    let currentResponseContainer = null;

    // Model seçimi değiştiğinde RAG durum göstergesini güncelle
    modelSelect.addEventListener('change', function () {
        const selectedModel = modelSelect.value;
        const ragInfoElement = document.createElement('div');
        ragInfoElement.className = 'rag-info';

        // Model tipini belirle (OpenRouter veya Qroq)
        const isOpenRouterModel = selectedModel.endsWith('-openrouter');
        const isQroqModel = selectedModel.endsWith('-qroq');

        // Model adını göster ve RAG bilgisini ayarla
        if (isOpenRouterModel) {
            ragInfoElement.textContent = 'OpenRouter modeli - Sorular için RAG sistemi kullanılabilir';
            ragInfoElement.style.color = '#E91E63'; // Pembe
        } else if (isQroqModel) {
            ragInfoElement.textContent = 'Qroq modeli - Sorular için RAG sistemi kullanılabilir';
            ragInfoElement.style.color = '#2196F3'; // Mavi
        } else {
            ragInfoElement.textContent = 'Standart model - Sorular için RAG sistemi kullanılabilir';
            ragInfoElement.style.color = '#9C27B0'; // Mor
        }

        // Önceki bilgi varsa kaldır
        const existingInfo = document.querySelector('.rag-info');
        if (existingInfo) {
            existingInfo.remove();
        }

        // Yeni bilgiyi ekle
        document.querySelector('.model-selector').appendChild(ragInfoElement);
    });

    // Sayfa yüklendiğinde seçili modele göre RAG bilgisini göster
    window.addEventListener('DOMContentLoaded', function () {
        const event = new Event('change');
        modelSelect.dispatchEvent(event);
    });

    // Connect to socket
    socket.on('connect', function () {
        console.log('Connected to server');
    });

    // Handle incoming chat responses
    socket.on('chat_response', function (data) {
        if (responseTimeout) {
            clearTimeout(responseTimeout);
            responseTimeout = null;
        }

        const chatId = data.chat_id;
        currentChatId = chatId;

        // Find or create response container
        if (!currentResponseContainer) {
            currentResponseContainer = document.createElement('div');
            currentResponseContainer.id = `ai-response-${chatId}`;
            currentResponseContainer.className = 'message ai-message';
            currentResponseContainer.innerHTML = '<div class="message-avatar"><i class="fas fa-robot"></i></div><div class="message-content"></div>';
            chatMessages.appendChild(currentResponseContainer);

            // RAG durumu göstergesi ekle
            const ragStatusIndicator = document.createElement('div');
            ragStatusIndicator.className = 'rag-status-indicator';
            ragStatusIndicator.id = `rag-status-${chatId}`;
            currentResponseContainer.appendChild(ragStatusIndicator);
        }

        const messageContent = currentResponseContainer.querySelector('.message-content');
        const ragStatusIndicator = document.getElementById(`rag-status-${chatId}`);

        // RAG durumunu güncelle
        if (data.status) {
            if (data.status === 'rag_searching') {
                ragStatusIndicator.textContent = 'RAG sisteminde aranıyor...';
                ragStatusIndicator.className = 'rag-status-indicator searching';
            } else if (data.status === 'rag_found') {
                ragStatusIndicator.textContent = 'İlgili bilgi bulundu';
                ragStatusIndicator.className = 'rag-status-indicator found';
            } else if (data.status === 'rag_not_found') {
                ragStatusIndicator.textContent = 'İlgili bilgi bulunamadı, model düşünüyor';
                ragStatusIndicator.className = 'rag-status-indicator not-found';
            } else if (data.status === 'thinking') {
                ragStatusIndicator.textContent = 'Model düşünüyor...';
                ragStatusIndicator.className = 'rag-status-indicator thinking';
            } else if (data.status === 'typing') {
                ragStatusIndicator.textContent = 'Model yanıt yazıyor...';
                ragStatusIndicator.className = 'rag-status-indicator typing';
            }
        }

        // Add new content
        if (data.content) {
            messageContent.textContent += data.content;
        }

        // If response is complete
        if (data.is_complete) {
            isWaitingForResponse = false;
            sendButton.disabled = false;

            // RAG durumu göstergesini gizle
            const ragStatusIndicator = document.getElementById(`rag-status-${chatId}`);
            if (ragStatusIndicator) {
                ragStatusIndicator.style.display = 'none';
            }

            currentResponseContainer = null; // Reset for next response

            // Update tokens display
            if (data.tokens_remaining !== undefined) {
                const tokensDisplay = document.querySelector('.tokens');
                if (tokensDisplay) {
                    tokensDisplay.textContent = `Tokens: ${data.tokens_remaining}`;
                }
            }

            // Add a "tokens used" note
            if (data.tokens_used) {
                const tokensUsedNote = document.createElement('div');
                tokensUsedNote.className = 'tokens-used';
                tokensUsedNote.textContent = `Tokens used: ${data.tokens_used}`;
                currentResponseContainer.appendChild(tokensUsedNote);
            }
        }

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

    // Handle errors
    socket.on('error', function (data) {
        if (responseTimeout) {
            clearTimeout(responseTimeout);
            responseTimeout = null;
        }

        isWaitingForResponse = false;
        sendButton.disabled = false;

        // Hata durumunda RAG durumu göstergesini gizle
        if (currentResponseContainer) {
            const chatId = currentResponseContainer.id.replace('ai-response-', '');
            const ragStatusIndicator = document.getElementById(`rag-status-${chatId}`);
            if (ragStatusIndicator) {
                ragStatusIndicator.style.display = 'none';
            }
        }

        currentResponseContainer = null; // Reset for next response

        const errorMessage = document.createElement('div');
        errorMessage.className = 'error-message';
        errorMessage.textContent = data.message || 'An error occurred';
        chatMessages.appendChild(errorMessage);

        chatMessages.scrollTop = chatMessages.scrollHeight;
    });

    // Send message function
    function sendMessage() {
        const message = messageInput.value.trim();
        const model = modelSelect.value;

        if (!message || isWaitingForResponse) return;

        // Clear input
        messageInput.value = '';

        // Add user message to chat
        const userMessageElement = document.createElement('div');
        userMessageElement.className = 'message user-message';
        userMessageElement.innerHTML = `
            <div class="message-avatar">
                <i class="fas fa-user"></i>
            </div>
            <div class="message-content">${message}</div>
        `;
        chatMessages.appendChild(userMessageElement);

        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Set waiting state
        isWaitingForResponse = true;
        sendButton.disabled = true;

        // Send message to server
        socket.emit('chat_message', {
            message: message,
            model: model,
            chat_id: currentChatId
        });

        // Set timeout for response (5 minutes)
        responseTimeout = setTimeout(function () {
            socket.emit('error', {
                message: 'Server timeout. Please try again later.'
            });
            isWaitingForResponse = false;
            sendButton.disabled = false;
            currentResponseContainer = null; // Reset for next response
        }, 5 * 60 * 1000);
    }

    // Event listeners
    sendButton.addEventListener('click', sendMessage);

    messageInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});