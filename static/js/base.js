/*
 * Medical Document Parser - Base JavaScript
 * Common functionality for the application
 */

// DOM Content Loaded Event
document.addEventListener('DOMContentLoaded', function() {
    console.log('Medical Document Parser loaded');
    
    // Initialize common components
    initializeDropdowns();
    initializeAlerts();
    initializeTooltips();
    
    // HIPAA-compliant session timeout warning
    initializeSessionTimeout();
});

// Dropdown Menu Functionality
function initializeDropdowns() {
    const dropdowns = document.querySelectorAll('.user-menu');
    
    dropdowns.forEach(dropdown => {
        const button = dropdown.querySelector('.user-button');
        const menu = dropdown.querySelector('.user-dropdown');
        
        if (button && menu) {
            // Toggle dropdown on click
            button.addEventListener('click', function(e) {
                e.stopPropagation();
                menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
            });
            
            // Close dropdown when clicking outside
            document.addEventListener('click', function() {
                menu.style.display = 'none';
            });
            
            // Keyboard navigation
            button.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
                }
            });
        }
    });
}

// Alert/Message Functionality
function initializeAlerts() {
    const alertCloseButtons = document.querySelectorAll('.message-close');
    
    alertCloseButtons.forEach(button => {
        button.addEventListener('click', function() {
            const alert = this.closest('.alert');
            if (alert) {
                alert.style.opacity = '0';
                setTimeout(() => {
                    alert.remove();
                }, 300);
            }
        });
    });
    
    // Auto-hide success messages after 5 seconds
    const successAlerts = document.querySelectorAll('.alert-success');
    successAlerts.forEach(alert => {
        setTimeout(() => {
            if (alert.parentNode) {
                alert.style.opacity = '0';
                setTimeout(() => {
                    alert.remove();
                }, 300);
            }
        }, 5000);
    });
}

// Tooltip Functionality
function initializeTooltips() {
    const tooltipElements = document.querySelectorAll('[data-tooltip]');
    
    tooltipElements.forEach(element => {
        element.addEventListener('mouseenter', showTooltip);
        element.addEventListener('mouseleave', hideTooltip);
        element.addEventListener('focus', showTooltip);
        element.addEventListener('blur', hideTooltip);
    });
}

function showTooltip(e) {
    const tooltipText = e.target.getAttribute('data-tooltip');
    if (!tooltipText) return;
    
    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.textContent = tooltipText;
    tooltip.id = 'tooltip-' + Date.now();
    
    document.body.appendChild(tooltip);
    
    const rect = e.target.getBoundingClientRect();
    tooltip.style.left = rect.left + (rect.width / 2) - (tooltip.offsetWidth / 2) + 'px';
    tooltip.style.top = rect.top - tooltip.offsetHeight - 5 + 'px';
    
    e.target.setAttribute('aria-describedby', tooltip.id);
}

function hideTooltip(e) {
    const tooltipId = e.target.getAttribute('aria-describedby');
    if (tooltipId) {
        const tooltip = document.getElementById(tooltipId);
        if (tooltip) {
            tooltip.remove();
        }
        e.target.removeAttribute('aria-describedby');
    }
}

// HIPAA-compliant Session Timeout
function initializeSessionTimeout() {
    let sessionTimeoutWarning;
    let sessionTimeoutLogout;
    const warningTime = 50 * 60 * 1000; // 50 minutes (10 min warning before 1 hour timeout)
    const logoutTime = 60 * 60 * 1000;  // 60 minutes total session
    
    function resetSessionTimeout() {
        clearTimeout(sessionTimeoutWarning);
        clearTimeout(sessionTimeoutLogout);
        
        // Show warning 10 minutes before timeout
        sessionTimeoutWarning = setTimeout(() => {
            showSessionWarning();
        }, warningTime);
        
        // Auto logout after full session time
        sessionTimeoutLogout = setTimeout(() => {
            window.location.href = '/accounts/logout/?timeout=1';
        }, logoutTime);
    }
    
    function showSessionWarning() {
        const modal = createSessionWarningModal();
        document.body.appendChild(modal);
        modal.style.display = 'block';
        
        // Auto-close warning after 10 minutes if no action
        setTimeout(() => {
            if (modal.parentNode) {
                modal.remove();
            }
        }, 10 * 60 * 1000);
    }
    
    function createSessionWarningModal() {
        const modal = document.createElement('div');
        modal.className = 'session-warning-modal';
        modal.innerHTML = `
            <div class="session-warning-content">
                <h3>Session Timeout Warning</h3>
                <p>Your session will expire in 10 minutes due to inactivity. For HIPAA compliance, you will be automatically logged out.</p>
                <div class="session-warning-actions">
                    <button class="btn btn-primary" onclick="extendSession()">Continue Working</button>
                    <button class="btn btn-secondary" onclick="logoutNow()">Logout Now</button>
                </div>
            </div>
        `;
        return modal;
    }
    
    // Extend session on user activity
    window.extendSession = function() {
        fetch('/accounts/extend-session/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'Content-Type': 'application/json'
            }
        }).then(() => {
            const modal = document.querySelector('.session-warning-modal');
            if (modal) modal.remove();
            resetSessionTimeout();
        });
    };
    
    // Logout immediately
    window.logoutNow = function() {
        window.location.href = '/accounts/logout/';
    };
    
    // Track user activity to reset session timer
    ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'].forEach(event => {
        document.addEventListener(event, resetSessionTimeout, true);
    });
    
    // Initial setup
    resetSessionTimeout();
}

// Utility Functions

// Get CSRF Token for AJAX requests
function getCSRFToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }
    return '';
}

// Show loading indicator
function showLoading(element) {
    if (!element) return;
    
    element.classList.add('loading');
    element.disabled = true;
    
    const originalText = element.textContent;
    element.setAttribute('data-original-text', originalText);
    element.textContent = 'Loading...';
}

// Hide loading indicator
function hideLoading(element) {
    if (!element) return;
    
    element.classList.remove('loading');
    element.disabled = false;
    
    const originalText = element.getAttribute('data-original-text');
    if (originalText) {
        element.textContent = originalText;
        element.removeAttribute('data-original-text');
    }
}

// Format file size for display
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Validate file types for medical documents
function validateFileType(file) {
    const allowedTypes = [
        'application/pdf',
        'image/jpeg',
        'image/png',
        'image/tiff',
        'text/plain'
    ];
    
    return allowedTypes.includes(file.type);
}

// HIPAA-compliant error logging (no PHI)
function logError(error, context = '') {
    const errorData = {
        message: error.message || 'Unknown error',
        context: context,
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent,
        url: window.location.href
    };
    
    // Send to logging endpoint (no PHI included)
    fetch('/api/log-error/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify(errorData)
    }).catch(console.error);
} 