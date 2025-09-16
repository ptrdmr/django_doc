/**
 * Patient Data Comparison Interactive Features
 * Handles field resolution, bulk operations, and modal interactions
 */

class PatientComparisonManager {
    constructor() {
        this.documentId = null;
        this.modalElement = null;
        this.currentField = null;
        
        this.init();
    }
    
    init() {
        // Get document ID from the page
        this.documentId = this.getDocumentId();
        
        // Initialize modal
        this.modalElement = document.getElementById('manual-edit-modal');
        
        // Bind event listeners
        this.bindFieldActionButtons();
        this.bindBulkActionButtons();
        this.bindModalControls();
        
        console.log('Patient Comparison Manager initialized for document:', this.documentId);
    }
    
    getDocumentId() {
        // Extract document ID from URL or data attribute
        const urlParts = window.location.pathname.split('/');
        const reviewIndex = urlParts.indexOf('review');
        if (reviewIndex > 0) {
            return urlParts[reviewIndex - 1];
        }
        
        // Fallback: check for data attribute
        const container = document.querySelector('.patient-comparison-container');
        return container ? container.dataset.documentId : null;
    }
    
    bindFieldActionButtons() {
        // Individual field action buttons
        document.addEventListener('click', (e) => {
            const button = e.target.closest('.action-btn');
            if (!button) return;
            
            e.preventDefault();
            
            const fieldName = button.dataset.field;
            const action = button.dataset.action;
            
            if (action === 'manual_edit') {
                this.openManualEditModal(fieldName, button);
            } else {
                this.resolveField(fieldName, action, button);
            }
        });
    }
    
    bindBulkActionButtons() {
        // Bulk action buttons
        document.addEventListener('click', (e) => {
            const button = e.target.closest('.bulk-action-btn');
            if (!button) return;
            
            e.preventDefault();
            
            const action = button.dataset.action;
            this.performBulkAction(action, button);
        });
    }
    
    bindModalControls() {
        if (!this.modalElement) return;
        
        // Close modal buttons
        this.modalElement.addEventListener('click', (e) => {
            if (e.target.classList.contains('close-modal') || 
                e.target.classList.contains('cancel-edit') ||
                e.target === this.modalElement) {
                this.closeModal();
            }
        });
        
        // Save edit button
        const saveButton = this.modalElement.querySelector('.save-edit');
        if (saveButton) {
            saveButton.addEventListener('click', () => {
                this.saveManualEdit();
            });
        }
        
        // ESC key to close modal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.modalElement.classList.contains('hidden')) {
                this.closeModal();
            }
        });
    }
    
    async resolveField(fieldName, resolution, buttonElement) {
        if (!this.documentId || !fieldName || !resolution) {
            this.showError('Missing required data for field resolution');
            return;
        }
        
        // Show loading state
        const originalText = buttonElement.textContent;
        buttonElement.disabled = true;
        buttonElement.textContent = 'Resolving...';
        
        try {
            const formData = new FormData();
            formData.append('action', 'resolve_field');
            formData.append('field_name', fieldName);
            formData.append('resolution', resolution);
            formData.append('reasoning', `User selected: ${resolution}`);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());
            
            const response = await fetch(`/documents/${this.documentId}/resolve/`, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.updateFieldUI(fieldName, resolution, buttonElement);
                this.updateProgressIndicators(result);
                this.showSuccess(`Field "${fieldName}" resolved successfully`);
            } else {
                throw new Error(result.error || 'Resolution failed');
            }
            
        } catch (error) {
            console.error('Error resolving field:', error);
            this.showError(`Failed to resolve field: ${error.message}`);
        } finally {
            // Restore button state
            buttonElement.disabled = false;
            buttonElement.textContent = originalText;
        }
    }
    
    async performBulkAction(action, buttonElement) {
        if (!this.documentId || !action) {
            this.showError('Missing required data for bulk action');
            return;
        }
        
        // Confirm bulk action
        const actionNames = {
            'keep_all_existing': 'keep all existing patient record data',
            'use_all_high_confidence': 'use all high-confidence document data',
            'apply_suggestions': 'apply all system suggestions'
        };
        
        const actionName = actionNames[action] || action;
        if (!confirm(`Are you sure you want to ${actionName}?`)) {
            return;
        }
        
        // Show loading state
        const originalText = buttonElement.textContent;
        buttonElement.disabled = true;
        buttonElement.textContent = 'Processing...';
        
        try {
            const formData = new FormData();
            formData.append('action', 'bulk_resolve');
            formData.append('bulk_action', action);
            formData.append('reasoning', `Bulk action: ${actionName}`);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());
            
            const response = await fetch(`/documents/${this.documentId}/resolve/`, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.updateBulkActionUI(action, result.resolved_count);
                this.updateProgressIndicators(result);
                this.showSuccess(`Bulk action completed: ${result.resolved_count} fields resolved`);
                
                // Refresh the page to show updated state
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                throw new Error(result.error || 'Bulk action failed');
            }
            
        } catch (error) {
            console.error('Error performing bulk action:', error);
            this.showError(`Bulk action failed: ${error.message}`);
        } finally {
            // Restore button state
            buttonElement.disabled = false;
            buttonElement.textContent = originalText;
        }
    }
    
    openManualEditModal(fieldName, buttonElement) {
        if (!this.modalElement) return;
        
        this.currentField = {
            name: fieldName,
            button: buttonElement
        };
        
        // Get current field data from the comparison row
        const row = buttonElement.closest('.comparison-row');
        const extractedValue = row.querySelector('.col-span-3:nth-child(2) .data-value .font-medium')?.textContent?.trim() || '';
        const patientValue = row.querySelector('.col-span-3:nth-child(3) .data-value .font-medium')?.textContent?.trim() || '';
        
        // Populate modal
        const fieldNameSpan = this.modalElement.querySelector('#edit-field-name');
        const valueInput = this.modalElement.querySelector('#edit-field-value');
        const reasoningTextarea = this.modalElement.querySelector('#edit-reasoning');
        
        if (fieldNameSpan) fieldNameSpan.textContent = fieldName;
        if (valueInput) {
            valueInput.value = extractedValue || patientValue || '';
            valueInput.focus();
        }
        if (reasoningTextarea) reasoningTextarea.value = '';
        
        // Show modal
        this.modalElement.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
    
    closeModal() {
        if (!this.modalElement) return;
        
        this.modalElement.classList.add('hidden');
        document.body.style.overflow = '';
        this.currentField = null;
    }
    
    async saveManualEdit() {
        if (!this.currentField || !this.modalElement) return;
        
        const valueInput = this.modalElement.querySelector('#edit-field-value');
        const reasoningTextarea = this.modalElement.querySelector('#edit-reasoning');
        
        const customValue = valueInput?.value?.trim() || '';
        const reasoning = reasoningTextarea?.value?.trim() || '';
        
        if (!customValue) {
            this.showError('Please enter a value');
            return;
        }
        
        if (!reasoning) {
            this.showError('Please provide a reason for this change');
            return;
        }
        
        try {
            const formData = new FormData();
            formData.append('action', 'manual_edit');
            formData.append('field_name', this.currentField.name);
            formData.append('custom_value', customValue);
            formData.append('reasoning', reasoning);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());
            
            const response = await fetch(`/documents/${this.documentId}/resolve/`, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.updateFieldUI(this.currentField.name, 'manual_edit', this.currentField.button, customValue);
                this.updateProgressIndicators(result);
                this.showSuccess(`Field "${this.currentField.name}" updated with custom value`);
                this.closeModal();
            } else {
                throw new Error(result.error || 'Manual edit failed');
            }
            
        } catch (error) {
            console.error('Error saving manual edit:', error);
            this.showError(`Failed to save changes: ${error.message}`);
        }
    }
    
    updateFieldUI(fieldName, resolution, buttonElement, customValue = null) {
        const row = buttonElement.closest('.comparison-row');
        if (!row) return;
        
        // Update visual state based on resolution
        row.classList.remove('border-yellow-200', 'bg-yellow-50', 'border-orange-200', 'bg-orange-50', 'border-red-200', 'bg-red-50');
        row.classList.add('border-green-200', 'bg-green-50');
        
        // Update action area to show resolution
        const actionContainer = row.querySelector('.action-container');
        if (actionContainer) {
            let resolutionText = '';
            let iconClass = '';
            
            switch (resolution) {
                case 'keep_existing':
                    resolutionText = 'Keeping Patient Record';
                    iconClass = 'text-green-600';
                    break;
                case 'use_extracted':
                    resolutionText = 'Using Document Data';
                    iconClass = 'text-blue-600';
                    break;
                case 'manual_edit':
                    resolutionText = customValue ? `Custom: ${customValue}` : 'Manual Edit Applied';
                    iconClass = 'text-purple-600';
                    break;
            }
            
            actionContainer.innerHTML = `
                <div class="resolution-applied flex items-center ${iconClass}">
                    <svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>
                    </svg>
                    <span class="text-xs font-medium">${resolutionText}</span>
                </div>
            `;
        }
    }
    
    updateBulkActionUI(action, resolvedCount) {
        // Update bulk actions panel to show completion
        const bulkActions = document.querySelector('.bulk-actions');
        if (bulkActions && resolvedCount > 0) {
            const successMessage = document.createElement('div');
            successMessage.className = 'bulk-success bg-green-100 border border-green-200 rounded p-3 mt-3';
            successMessage.innerHTML = `
                <div class="flex items-center text-green-800">
                    <svg class="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>
                    </svg>
                    <span class="text-sm font-medium">Resolved ${resolvedCount} fields with bulk action</span>
                </div>
            `;
            
            bulkActions.appendChild(successMessage);
            
            // Remove after 3 seconds
            setTimeout(() => {
                successMessage.remove();
            }, 3000);
        }
    }
    
    updateProgressIndicators(result) {
        // Update completion percentage
        const percentageElements = document.querySelectorAll('[data-completion-percentage]');
        percentageElements.forEach(el => {
            el.textContent = `${result.completion_percentage}%`;
        });
        
        // Update resolved count
        const resolvedElements = document.querySelectorAll('[data-fields-resolved]');
        resolvedElements.forEach(el => {
            el.textContent = result.fields_resolved;
        });
        
        // Update summary in header
        const summaryResolved = document.querySelector('.summary-item .text-green-600');
        if (summaryResolved) {
            summaryResolved.textContent = result.fields_resolved;
        }
        
        // Hide bulk actions if all resolved
        if (!result.has_pending) {
            const bulkActions = document.querySelector('.bulk-actions');
            if (bulkActions) {
                bulkActions.style.display = 'none';
            }
        }
    }
    
    getCsrfToken() {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (!csrfToken) {
            console.error('CSRF token not found');
        }
        return csrfToken || '';
    }
    
    showSuccess(message) {
        this.showNotification(message, 'success');
    }
    
    showError(message) {
        this.showNotification(message, 'error');
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification fixed top-4 right-4 px-6 py-3 rounded-lg shadow-lg z-50 transition-all duration-300 transform translate-x-full ${
            type === 'success' ? 'bg-green-600 text-white' :
            type === 'error' ? 'bg-red-600 text-white' :
            'bg-blue-600 text-white'
        }`;
        
        notification.innerHTML = `
            <div class="flex items-center">
                <svg class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    ${type === 'success' ? 
                        '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path>' :
                      type === 'error' ?
                        '<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"></path>' :
                        '<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path>'
                    }
                </svg>
                <span>${message}</span>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // Animate in
        setTimeout(() => {
            notification.classList.remove('translate-x-full');
        }, 100);
        
        // Auto-remove after 4 seconds
        setTimeout(() => {
            notification.classList.add('translate-x-full');
            setTimeout(() => {
                notification.remove();
            }, 300);
        }, 4000);
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if we're on a document review page with comparison data
    if (document.querySelector('.patient-comparison-container')) {
        window.patientComparison = new PatientComparisonManager();
    }
});

// Utility functions for template usage
window.PatientComparisonUtils = {
    /**
     * Toggle comparison mode visibility
     */
    toggleComparisonMode() {
        const comparison = document.querySelector('.patient-comparison-container');
        const standardReview = document.querySelector('.review-content');
        
        if (comparison && standardReview) {
            const isComparisonVisible = !comparison.classList.contains('hidden');
            
            if (isComparisonVisible) {
                comparison.classList.add('hidden');
                standardReview.classList.remove('hidden');
            } else {
                comparison.classList.remove('hidden');
                standardReview.classList.add('hidden');
            }
        }
    },
    
    /**
     * Expand/collapse comparison sections
     */
    toggleSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.classList.toggle('collapsed');
        }
    }
};
