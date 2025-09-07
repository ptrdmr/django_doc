/**
 * Document Viewer Module using PDF.js
 * 
 * Provides PDF viewing functionality with zoom and navigation controls
 * for the document review interface.
 */

class DocumentViewer {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.canvas = null;
        this.context = null;
        this.pdfDoc = null;
        this.currentPage = 1;
        this.scale = 1.2;
        this.isLoading = false;
        
        // Configuration options
        this.options = {
            minScale: 0.5,
            maxScale: 3.0,
            scaleStep: 0.2,
            ...options
        };
        
        this.init();
    }
    
    /**
     * Initialize the document viewer interface
     */
    init() {
        if (!this.container) {
            console.error('Document viewer container not found');
            return;
        }
        
        this.createViewerInterface();
        this.attachEventListeners();
    }
    
    /**
     * Create the PDF viewer interface elements
     */
    createViewerInterface() {
        this.container.innerHTML = `
            <div class="document-viewer">
                <!-- Toolbar -->
                <div class="viewer-toolbar bg-gray-100 border-b border-gray-200 p-3 flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                        <!-- Navigation Controls -->
                        <button id="prev-page" class="btn btn-sm btn-secondary" disabled>
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
                            </svg>
                        </button>
                        
                        <span class="text-sm text-gray-600">
                            Page 
                            <input id="page-input" type="number" min="1" value="1" class="w-12 px-1 text-center border rounded">
                            of 
                            <span id="page-count">-</span>
                        </span>
                        
                        <button id="next-page" class="btn btn-sm btn-secondary" disabled>
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                            </svg>
                        </button>
                    </div>
                    
                    <div class="flex items-center space-x-2">
                        <!-- Zoom Controls -->
                        <button id="zoom-out" class="btn btn-sm btn-secondary">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 12H4"></path>
                            </svg>
                        </button>
                        
                        <span id="zoom-level" class="text-sm text-gray-600 w-12 text-center">120%</span>
                        
                        <button id="zoom-in" class="btn btn-sm btn-secondary">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                            </svg>
                        </button>
                        
                        <button id="fit-width" class="btn btn-sm btn-secondary text-xs">
                            Fit Width
                        </button>
                    </div>
                </div>
                
                <!-- PDF Canvas Container -->
                <div class="viewer-content bg-gray-200 flex-1 overflow-auto p-4">
                    <div class="flex justify-center">
                        <div id="canvas-container" class="bg-white shadow-lg">
                            <canvas id="pdf-canvas"></canvas>
                        </div>
                    </div>
                </div>
                
                <!-- Loading Indicator -->
                <div id="loading-indicator" class="absolute inset-0 bg-white bg-opacity-75 flex items-center justify-center hidden">
                    <div class="text-center">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
                        <p class="text-sm text-gray-600">Loading document...</p>
                    </div>
                </div>
                
                <!-- Error Display -->
                <div id="error-display" class="hidden p-4 bg-red-50 border border-red-200 text-red-700">
                    <p class="font-medium">Error loading document</p>
                    <p id="error-message" class="text-sm mt-1"></p>
                </div>
            </div>
        `;
        
        // Get canvas and context
        this.canvas = this.container.querySelector('#pdf-canvas');
        this.context = this.canvas.getContext('2d');
    }
    
    /**
     * Attach event listeners to control elements
     */
    attachEventListeners() {
        // Navigation controls
        this.container.querySelector('#prev-page').addEventListener('click', () => this.prevPage());
        this.container.querySelector('#next-page').addEventListener('click', () => this.nextPage());
        this.container.querySelector('#page-input').addEventListener('change', (e) => this.goToPage(parseInt(e.target.value)));
        
        // Zoom controls
        this.container.querySelector('#zoom-in').addEventListener('click', () => this.zoomIn());
        this.container.querySelector('#zoom-out').addEventListener('click', () => this.zoomOut());
        this.container.querySelector('#fit-width').addEventListener('click', () => this.fitWidth());
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.target.closest('.document-viewer')) {
                this.handleKeyboardShortcuts(e);
            }
        });
    }
    
    /**
     * Handle keyboard shortcuts
     */
    handleKeyboardShortcuts(event) {
        if (event.ctrlKey || event.metaKey) {
            switch (event.key) {
                case '=':
                case '+':
                    event.preventDefault();
                    this.zoomIn();
                    break;
                case '-':
                    event.preventDefault();
                    this.zoomOut();
                    break;
            }
        } else {
            switch (event.key) {
                case 'ArrowLeft':
                    event.preventDefault();
                    this.prevPage();
                    break;
                case 'ArrowRight':
                    event.preventDefault();
                    this.nextPage();
                    break;
            }
        }
    }
    
    /**
     * Load a PDF document from URL
     */
    async loadDocument(documentUrl) {
        if (!window.pdfjsLib) {
            this.showError('PDF.js library not loaded');
            return;
        }
        
        this.showLoading(true);
        this.hideError();
        
        try {
            // Configure PDF.js worker
            if (window.pdfjsLib.GlobalWorkerOptions) {
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            }
            
            // Load the PDF document
            const loadingTask = window.pdfjsLib.getDocument(documentUrl);
            this.pdfDoc = await loadingTask.promise;
            
            // Update UI
            this.currentPage = 1;
            this.updatePageInfo();
            this.updateNavigationButtons();
            
            // Render first page
            await this.renderPage(this.currentPage);
            
        } catch (error) {
            console.error('Error loading PDF:', error);
            this.showError(`Failed to load document: ${error.message}`);
        } finally {
            this.showLoading(false);
        }
    }
    
    /**
     * Render a specific page
     */
    async renderPage(pageNum) {
        if (!this.pdfDoc || this.isLoading) return;
        
        this.isLoading = true;
        this.showLoading(true);
        
        try {
            const page = await this.pdfDoc.getPage(pageNum);
            const viewport = page.getViewport({ scale: this.scale });
            
            // Set canvas dimensions
            this.canvas.width = viewport.width;
            this.canvas.height = viewport.height;
            
            // Render the page
            const renderContext = {
                canvasContext: this.context,
                viewport: viewport
            };
            
            await page.render(renderContext).promise;
            
            this.currentPage = pageNum;
            this.updatePageInfo();
            this.updateNavigationButtons();
            
        } catch (error) {
            console.error('Error rendering page:', error);
            this.showError(`Failed to render page: ${error.message}`);
        } finally {
            this.isLoading = false;
            this.showLoading(false);
        }
    }
    
    /**
     * Navigation methods
     */
    async prevPage() {
        if (this.currentPage > 1) {
            await this.renderPage(this.currentPage - 1);
        }
    }
    
    async nextPage() {
        if (this.pdfDoc && this.currentPage < this.pdfDoc.numPages) {
            await this.renderPage(this.currentPage + 1);
        }
    }
    
    async goToPage(pageNum) {
        if (this.pdfDoc && pageNum >= 1 && pageNum <= this.pdfDoc.numPages) {
            await this.renderPage(pageNum);
        }
    }
    
    /**
     * Zoom methods
     */
    async zoomIn() {
        if (this.scale < this.options.maxScale) {
            this.scale += this.options.scaleStep;
            this.scale = Math.min(this.scale, this.options.maxScale);
            await this.renderPage(this.currentPage);
            this.updateZoomDisplay();
        }
    }
    
    async zoomOut() {
        if (this.scale > this.options.minScale) {
            this.scale -= this.options.scaleStep;
            this.scale = Math.max(this.scale, this.options.minScale);
            await this.renderPage(this.currentPage);
            this.updateZoomDisplay();
        }
    }
    
    async fitWidth() {
        if (!this.pdfDoc) return;
        
        const page = await this.pdfDoc.getPage(this.currentPage);
        const containerWidth = this.container.querySelector('.viewer-content').clientWidth - 32; // Account for padding
        const viewport = page.getViewport({ scale: 1.0 });
        
        this.scale = containerWidth / viewport.width;
        this.scale = Math.max(this.options.minScale, Math.min(this.scale, this.options.maxScale));
        
        await this.renderPage(this.currentPage);
        this.updateZoomDisplay();
    }
    
    /**
     * UI update methods
     */
    updatePageInfo() {
        const pageInput = this.container.querySelector('#page-input');
        const pageCount = this.container.querySelector('#page-count');
        
        if (pageInput) pageInput.value = this.currentPage;
        if (pageCount) pageCount.textContent = this.pdfDoc ? this.pdfDoc.numPages : '-';
    }
    
    updateNavigationButtons() {
        const prevBtn = this.container.querySelector('#prev-page');
        const nextBtn = this.container.querySelector('#next-page');
        
        if (prevBtn) prevBtn.disabled = this.currentPage <= 1;
        if (nextBtn) nextBtn.disabled = !this.pdfDoc || this.currentPage >= this.pdfDoc.numPages;
    }
    
    updateZoomDisplay() {
        const zoomLevel = this.container.querySelector('#zoom-level');
        if (zoomLevel) {
            zoomLevel.textContent = Math.round(this.scale * 100) + '%';
        }
    }
    
    /**
     * Utility methods
     */
    showLoading(show) {
        const indicator = this.container.querySelector('#loading-indicator');
        if (indicator) {
            indicator.classList.toggle('hidden', !show);
        }
    }
    
    showError(message) {
        const errorDisplay = this.container.querySelector('#error-display');
        const errorMessage = this.container.querySelector('#error-message');
        
        if (errorDisplay && errorMessage) {
            errorMessage.textContent = message;
            errorDisplay.classList.remove('hidden');
        }
    }
    
    hideError() {
        const errorDisplay = this.container.querySelector('#error-display');
        if (errorDisplay) {
            errorDisplay.classList.add('hidden');
        }
    }
    
    /**
     * Get current document info
     */
    getDocumentInfo() {
        return {
            numPages: this.pdfDoc ? this.pdfDoc.numPages : 0,
            currentPage: this.currentPage,
            scale: this.scale,
            isLoaded: !!this.pdfDoc
        };
    }
    
    /**
     * Clean up resources
     */
    destroy() {
        if (this.pdfDoc) {
            this.pdfDoc.destroy();
            this.pdfDoc = null;
        }
    }
}

// Export for use in other modules
window.DocumentViewer = DocumentViewer;
