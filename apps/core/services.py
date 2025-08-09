"""
Cost monitoring and API usage tracking services.
Handles calculation of AI API costs and usage analytics.
"""

import logging
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from django.db import models
from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from .models import APIUsageLog

logger = logging.getLogger(__name__)


class CostCalculator:
    """
    Service for calculating AI API costs based on current pricing.
    Updates pricing as providers change their rates.
    """
    
    # Current pricing as of January 2025 (per 1000 tokens)
    MODEL_PRICING = {
        'anthropic': {
            'claude-3-opus-20240229': {'input': 0.015, 'output': 0.075},
            'claude-3-sonnet-20240229': {'input': 0.003, 'output': 0.015},
            'claude-3-haiku-20240307': {'input': 0.00025, 'output': 0.00125},
            # Legacy model names
            'claude-3-opus': {'input': 0.015, 'output': 0.075},
            'claude-3-sonnet': {'input': 0.003, 'output': 0.015},
            'claude-3-haiku': {'input': 0.00025, 'output': 0.00125},
        },
        'openai': {
            'gpt-4': {'input': 0.03, 'output': 0.06},
            'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
            'gpt-4-turbo-preview': {'input': 0.01, 'output': 0.03},
            'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},
            'gpt-3.5-turbo-16k': {'input': 0.003, 'output': 0.004},
        }
    }
    
    @classmethod
    def calculate_cost(cls, provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        """
        Calculate the cost in USD for a specific API call.
        
        Args:
            provider: API provider (anthropic, openai)
            model: Model name (claude-3-sonnet, gpt-3.5-turbo, etc.)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            
        Returns:
            Cost in USD as Decimal
        """
        try:
            pricing = cls.MODEL_PRICING[provider.lower()][model.lower()]
            
            # Convert tokens to thousands for pricing calculation
            input_cost = Decimal(str(input_tokens)) * Decimal(str(pricing['input'])) / 1000
            output_cost = Decimal(str(output_tokens)) * Decimal(str(pricing['output'])) / 1000
            
            total_cost = input_cost + output_cost
            
            logger.debug(f"Cost calculation: {provider}/{model} - "
                        f"Input: {input_tokens} tokens @ ${pricing['input']}/1k = ${input_cost:.6f}, "
                        f"Output: {output_tokens} tokens @ ${pricing['output']}/1k = ${output_cost:.6f}, "
                        f"Total: ${total_cost:.6f}")
            
            return total_cost
            
        except KeyError as e:
            logger.warning(f"Unknown model pricing: {provider}/{model} - {e}")
            logger.warning(f"Available models: {list(cls.MODEL_PRICING.get(provider.lower(), {}).keys())}")
            return Decimal('0.00')
        except Exception as e:
            logger.error(f"Error calculating cost for {provider}/{model}: {e}")
            return Decimal('0.00')
    
    @classmethod
    def get_available_models(cls) -> Dict[str, list]:
        """Get list of available models with pricing."""
        return {
            provider: list(models.keys()) 
            for provider, models in cls.MODEL_PRICING.items()
        }
    
    @classmethod
    def get_model_pricing(cls, provider: str, model: str) -> Optional[Dict[str, float]]:
        """Get pricing for a specific model."""
        try:
            return cls.MODEL_PRICING[provider.lower()][model.lower()]
        except KeyError:
            return None


class APIUsageMonitor:
    """
    Service for monitoring and tracking API usage.
    Handles logging, analytics, and cost optimization.
    """
    
    @classmethod
    def log_api_usage(cls, document, patient, session_id, provider, model,
                     input_tokens, output_tokens, total_tokens,
                     start_time, end_time, success=True, error_message=None,
                     chunk_number=None, total_chunks=None) -> APIUsageLog:
        """
        Log API usage to database with cost calculation.
        
        Args:
            document: Document instance being processed
            patient: Patient instance (can be None)
            session_id: UUID for processing session
            provider: API provider name
            model: Model name used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens  
            total_tokens: Total tokens used
            start_time: When API call started
            end_time: When API call completed
            success: Whether call succeeded
            error_message: Error message if failed
            chunk_number: For chunked docs, which chunk
            total_chunks: Total chunks for document
            
        Returns:
            Created APIUsageLog instance
        """
        try:
            # Calculate duration
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            # Calculate cost
            cost = CostCalculator.calculate_cost(provider, model, input_tokens, output_tokens)
            
            # Create log entry
            usage_log = APIUsageLog.objects.create(
                document=document,
                patient=patient,
                processing_session=session_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                processing_started=start_time,
                processing_completed=end_time,
                processing_duration_ms=duration_ms,
                success=success,
                error_message=error_message,
                chunk_number=chunk_number,
                total_chunks=total_chunks,
            )
            
            if success:
                logger.info(f"API usage logged: {provider}/{model} - "
                           f"{total_tokens} tokens, ${cost:.6f}, {duration_ms}ms")
            else:
                logger.warning(f"Failed API call logged: {provider}/{model} - "
                              f"Error: {error_message}, Duration: {duration_ms}ms")
            
            return usage_log
            
        except Exception as e:
            logger.error(f"Failed to log API usage: {e}")
            raise
    
    @classmethod
    def get_usage_by_patient(cls, patient, date_from=None, date_to=None) -> Dict[str, Any]:
        """
        Get usage statistics for a specific patient.
        
        Args:
            patient: Patient instance
            date_from: Start date for filtering
            date_to: End date for filtering
            
        Returns:
            Dictionary with usage statistics
        """
        query = APIUsageLog.objects.filter(patient=patient)
        
        if date_from:
            query = query.filter(processing_started__gte=date_from)
        if date_to:
            query = query.filter(processing_completed__lte=date_to)
        
        # Aggregate statistics
        stats = query.aggregate(
            total_cost=Sum('cost_usd'),
            total_tokens=Sum('total_tokens'),
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            avg_duration_ms=Avg('processing_duration_ms'),
            api_call_count=Count('id')
        )
        
        # Additional metrics
        document_count = query.values('document').distinct().count()
        success_rate = (query.filter(success=True).count() / max(stats['api_call_count'], 1)) * 100
        
        return {
            'total_cost': stats['total_cost'] or Decimal('0.00'),
            'total_tokens': stats['total_tokens'] or 0,
            'total_input_tokens': stats['total_input_tokens'] or 0,
            'total_output_tokens': stats['total_output_tokens'] or 0,
            'document_count': document_count,
            'api_calls': stats['api_call_count'] or 0,
            'avg_duration_ms': stats['avg_duration_ms'] or 0,
            'success_rate': success_rate,
            'avg_cost_per_document': (stats['total_cost'] or Decimal('0.00')) / max(document_count, 1),
            'avg_tokens_per_document': (stats['total_tokens'] or 0) / max(document_count, 1),
        }
    
    @classmethod
    def get_usage_by_document(cls, document) -> Dict[str, Any]:
        """Get usage statistics for a specific document."""
        query = APIUsageLog.objects.filter(document=document)
        
        # Get session-level stats (for chunked documents)
        sessions = query.values('processing_session').annotate(
            session_cost=Sum('cost_usd'),
            session_tokens=Sum('total_tokens'),
            session_duration=Sum('processing_duration_ms'),
            chunk_count=Count('id')
        )
        
        total_stats = query.aggregate(
            total_cost=Sum('cost_usd'),
            total_tokens=Sum('total_tokens'),
            total_duration_ms=Sum('processing_duration_ms'),
            call_count=Count('id')
        )
        
        return {
            'total_cost': total_stats['total_cost'] or Decimal('0.00'),
            'total_tokens': total_stats['total_tokens'] or 0,
            'total_duration_ms': total_stats['total_duration_ms'] or 0,
            'api_calls': total_stats['call_count'] or 0,
            'sessions': list(sessions),
            'was_chunked': query.filter(chunk_number__isnull=False).exists(),
        }
    
    @classmethod
    def get_usage_summary(cls, date_from=None, date_to=None) -> Dict[str, Any]:
        """
        Get overall usage summary across all documents and patients.
        
        Args:
            date_from: Start date for filtering
            date_to: End date for filtering
            
        Returns:
            Dictionary with overall usage statistics
        """
        query = APIUsageLog.objects.all()
        
        if date_from:
            query = query.filter(processing_started__gte=date_from)
        if date_to:
            query = query.filter(processing_completed__lte=date_to)
        
        # Overall statistics
        overall_stats = query.aggregate(
            total_cost=Sum('cost_usd'),
            total_tokens=Sum('total_tokens'),
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            avg_duration_ms=Avg('processing_duration_ms'),
            api_call_count=Count('id')
        )
        
        # Model usage breakdown
        model_usage = query.values('provider', 'model').annotate(
            call_count=Count('id'),
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('cost_usd'),
            avg_duration=Avg('processing_duration_ms'),
            success_rate=Count('id', filter=Q(success=True)) * 100.0 / Count('id')
        ).order_by('-total_cost')
        
        # Daily usage trends (last 30 days if no date range specified)
        if not date_from:
            date_from = timezone.now() - timedelta(days=30)
        
        daily_usage = query.filter(
            processing_started__gte=date_from
        ).extra(
            select={'day': "date(processing_started)"}
        ).values('day').annotate(
            call_count=Count('id'),
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('cost_usd')
        ).order_by('day')
        
        # Additional metrics
        unique_documents = query.values('document').distinct().count()
        unique_patients = query.values('patient').distinct().count()
        success_rate = (query.filter(success=True).count() / max(overall_stats['api_call_count'], 1)) * 100
        
        return {
            'summary': {
                'total_cost': overall_stats['total_cost'] or Decimal('0.00'),
                'total_tokens': overall_stats['total_tokens'] or 0,
                'total_input_tokens': overall_stats['total_input_tokens'] or 0,
                'total_output_tokens': overall_stats['total_output_tokens'] or 0,
                'total_documents': unique_documents,
                'total_patients': unique_patients,
                'total_api_calls': overall_stats['api_call_count'] or 0,
                'avg_duration_ms': overall_stats['avg_duration_ms'] or 0,
                'success_rate': success_rate,
                'avg_cost_per_document': (overall_stats['total_cost'] or Decimal('0.00')) / max(unique_documents, 1),
                'avg_tokens_per_document': (overall_stats['total_tokens'] or 0) / max(unique_documents, 1),
            },
            'model_usage': list(model_usage),
            'daily_usage': list(daily_usage),
        }
    
    @classmethod
    def get_cost_optimization_suggestions(cls, days=30) -> Dict[str, Any]:
        """
        Analyze usage patterns and suggest cost optimizations.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with optimization suggestions
        """
        date_from = timezone.now() - timedelta(days=days)
        query = APIUsageLog.objects.filter(processing_started__gte=date_from)
        
        # Model performance analysis
        model_performance = query.values('provider', 'model').annotate(
            call_count=Count('id'),
            total_cost=Sum('cost_usd'),
            avg_cost_per_token=Avg(F('cost_usd') / F('total_tokens')),
            success_rate=Count('id', filter=Q(success=True)) * 100.0 / Count('id'),
            avg_duration=Avg('processing_duration_ms')
        ).order_by('avg_cost_per_token')
        
        suggestions = []
        
        # Find most cost-effective model
        if model_performance:
            cheapest = model_performance[0]
            most_expensive = model_performance.reverse()[0]
            
            if cheapest['avg_cost_per_token'] and most_expensive['avg_cost_per_token']:
                savings_potential = (
                    most_expensive['avg_cost_per_token'] - cheapest['avg_cost_per_token']
                ) * query.aggregate(Sum('total_tokens'))['total_tokens__sum']
                
                suggestions.append({
                    'type': 'model_optimization',
                    'message': f"Consider using {cheapest['provider']}/{cheapest['model']} "
                              f"(${cheapest['avg_cost_per_token']:.6f}/token) instead of "
                              f"{most_expensive['provider']}/{most_expensive['model']} "
                              f"(${most_expensive['avg_cost_per_token']:.6f}/token)",
                    'potential_savings': savings_potential
                })
        
        # Analyze failure rates
        high_failure_models = query.values('provider', 'model').annotate(
            call_count=Count('id'),
            failure_count=Count('id', filter=Q(success=False)),
            failure_rate=Count('id', filter=Q(success=False)) * 100.0 / Count('id')
        ).filter(failure_rate__gt=10).order_by('-failure_rate')
        
        for model in high_failure_models:
            suggestions.append({
                'type': 'reliability_concern',
                'message': f"{model['provider']}/{model['model']} has {model['failure_rate']:.1f}% "
                          f"failure rate ({model['failure_count']}/{model['call_count']} calls)",
                'impact': 'high' if model['failure_rate'] > 25 else 'medium'
            })
        
        return {
            'model_performance': list(model_performance),
            'suggestions': suggestions,
            'analysis_period': f"{days} days",
            'total_calls_analyzed': query.count()
        } 


class ErrorRecoveryService:
    """
    Comprehensive error recovery and resilience service for document processing.
    Implements circuit breaker, graceful degradation, and intelligent retry patterns.
    Like having a full emergency toolkit when your truck breaks down on a country road.
    """
    
    # Error categorization for intelligent handling
    ERROR_CATEGORIES = {
        'transient': [
            'connection_error',
            'timeout',
            'server_overloaded',
            'network_error'
        ],
        'rate_limit': [
            'rate_limit_exceeded',
            'rate_limit_error',
            'too_many_requests'
        ],
        'authentication': [
            'authentication_error',
            'invalid_api_key',
            'unauthorized'
        ],
        'permanent': [
            'api_status_error',
            'model_not_found',
            'invalid_model',
            'quota_exceeded'
        ],
        'malformed': [
            'invalid_request',
            'malformed_content',
            'content_policy_violation'
        ]
    }
    
    # Retry strategies based on error type
    RETRY_STRATEGIES = {
        'transient': {
            'max_retries': 5,
            'base_delay': 2,  # seconds
            'max_delay': 300,  # 5 minutes
            'backoff_multiplier': 2,
            'jitter': True
        },
        'rate_limit': {
            'max_retries': 3,
            'base_delay': 60,  # 1 minute
            'max_delay': 900,  # 15 minutes
            'backoff_multiplier': 2,
            'jitter': False
        },
        'authentication': {
            'max_retries': 1,  # Don't retry auth errors much
            'base_delay': 5,
            'max_delay': 30,
            'backoff_multiplier': 1,
            'jitter': False
        }
    }

    def __init__(self):
        """Initialize error recovery service with circuit breaker state."""
        self.logger = logging.getLogger(__name__)
        self._circuit_breakers = {}  # Service-specific circuit breakers
        
    def categorize_error(self, error_message: str, error_type: str = None) -> str:
        """
        Categorize error to determine appropriate recovery strategy.
        Like diagnosing whether your truck won't start due to a dead battery or empty gas tank.
        
        Args:
            error_message: The error message from the API
            error_type: Specific error type if known
            
        Returns:
            Error category for determining recovery strategy
        """
        error_lower = error_message.lower()
        
        # Check for specific error types first
        if error_type:
            for category, error_types in self.ERROR_CATEGORIES.items():
                if error_type in error_types:
                    return category
        
        # Check error message content - order matters for overlapping patterns
        if any(term in error_lower for term in ['rate limit', 'too many requests', 'quota exceeded']):
            return 'rate_limit'
        elif 'try again later' in error_lower or 'retry after' in error_lower:
            return 'rate_limit'  # Usually indicates rate limiting
        elif any(term in error_lower for term in ['connection', 'timeout', 'network', 'temporary', 'temporarily unavailable', 'server overloaded']):
            return 'transient'
        elif any(term in error_lower for term in ['auth', 'key', 'unauthorized', 'forbidden']):
            return 'authentication'
        elif any(term in error_lower for term in ['invalid', 'malformed', 'bad request']):
            return 'malformed'
        else:
            return 'permanent'
    
    def should_retry(self, error_category: str, attempt_number: int, 
                    last_attempt_time: datetime = None) -> bool:
        """
        Determine if we should retry based on error category and attempt history.
        Like checking if it's worth trying to jump-start the truck one more time.
        
        Args:
            error_category: Category of the error
            attempt_number: Current attempt number (1-based)
            last_attempt_time: When the last attempt was made
            
        Returns:
            Whether to attempt retry
        """
        if error_category == 'permanent':
            return False
            
        strategy = self.RETRY_STRATEGIES.get(error_category, self.RETRY_STRATEGIES['transient'])
        
        if attempt_number > strategy['max_retries']:
            return False
            
        # Check circuit breaker state
        if self._is_circuit_open(error_category):
            return False
            
        return True
    
    def calculate_retry_delay(self, error_category: str, attempt_number: int) -> int:
        """
        Calculate delay before next retry using exponential backoff with jitter.
        Like giving the engine time to cool down before trying again.
        
        Args:
            error_category: Category of the error
            attempt_number: Current attempt number (1-based)
            
        Returns:
            Delay in seconds before next retry
        """
        strategy = self.RETRY_STRATEGIES.get(error_category, self.RETRY_STRATEGIES['transient'])
        
        # Calculate exponential backoff
        delay = strategy['base_delay'] * (strategy['backoff_multiplier'] ** (attempt_number - 1))
        delay = min(delay, strategy['max_delay'])
        
        # Add jitter to prevent thundering herd
        if strategy['jitter']:
            import random
            jitter = random.uniform(0.5, 1.5)
            delay *= jitter
            
        return int(delay)
    
    def record_failure(self, service: str, error_category: str):
        """
        Record a service failure for circuit breaker pattern.
        Like noting that the starter motor is acting up again.
        
        Args:
            service: Service name (e.g., 'anthropic', 'openai')
            error_category: Category of the error
        """
        now = timezone.now()
        
        if service not in self._circuit_breakers:
            self._circuit_breakers[service] = {
                'failure_count': 0,
                'last_failure': None,
                'state': 'closed',  # closed, open, half_open
                'next_attempt': now
            }
        
        breaker = self._circuit_breakers[service]
        breaker['failure_count'] += 1
        breaker['last_failure'] = now
        
        # Open circuit if too many failures
        if breaker['failure_count'] >= 5:
            breaker['state'] = 'open'
            breaker['next_attempt'] = now + timedelta(minutes=10)  # Cool-down period
            
            self.logger.warning(f"Circuit breaker opened for {service} due to repeated failures")
    
    def record_success(self, service: str):
        """
        Record a service success for circuit breaker pattern.
        Like noting that the truck started right up this time.
        
        Args:
            service: Service name (e.g., 'anthropic', 'openai')
        """
        if service in self._circuit_breakers:
            breaker = self._circuit_breakers[service]
            
            if breaker['state'] == 'half_open':
                # Success in half-open state - close the circuit
                breaker['state'] = 'closed'
                breaker['failure_count'] = 0
                self.logger.info(f"Circuit breaker closed for {service} after successful recovery")
            elif breaker['state'] == 'closed':
                # Reset failure count on success
                breaker['failure_count'] = max(0, breaker['failure_count'] - 1)
    
    def _is_circuit_open(self, service: str) -> bool:
        """
        Check if circuit breaker is open for a service.
        Like checking if we should even bother trying to start the truck.
        
        Args:
            service: Service name to check
            
        Returns:
            True if circuit is open (service should not be attempted)
        """
        if service not in self._circuit_breakers:
            return False
            
        breaker = self._circuit_breakers[service]
        now = timezone.now()
        
        if breaker['state'] == 'open':
            if now >= breaker['next_attempt']:
                # Move to half-open state for testing
                breaker['state'] = 'half_open'
                self.logger.info(f"Circuit breaker for {service} moving to half-open state")
                return False
            else:
                return True
                
        return False
    
    def create_graceful_degradation_response(self, document_id: int, 
                                           partial_results: Dict[str, Any] = None,
                                           error_context: str = "") -> Dict[str, Any]:
        """
        Create a graceful degradation response when all AI services fail.
        Like getting the truck to limp home even when the engine's misfiring.
        
        Args:
            document_id: ID of the document being processed
            partial_results: Any partial results that were extracted
            error_context: Context about what went wrong
            
        Returns:
            Degraded response with manual review flags
        """
        response = {
            'success': False,
            'degraded': True,
            'requires_manual_review': True,
            'document_id': document_id,
            'error_context': error_context,
            'extraction_status': 'failed_with_degradation',
            'fields': partial_results or {},
            'recommendations': [
                'Document requires manual review due to AI processing failure',
                'Check document quality and format',
                'Verify API service status',
                'Consider reprocessing when services are restored'
            ],
            'manual_review_priority': 'high',
            'timestamp': timezone.now().isoformat()
        }
        
        # Log the degraded response
        self.logger.warning(
            f"Graceful degradation activated for document {document_id}: {error_context}"
        )
        
        # Create audit log entry
        from .models import AuditLog
        AuditLog.log_event(
            event_type='system_degradation',
            description=f"Document processing degraded for document {document_id}",
            details={
                'document_id': document_id,
                'error_context': error_context,
                'partial_results_available': bool(partial_results),
                'manual_review_required': True
            },
            severity='warning'
        )
        
        return response
    
    def get_service_health_status(self) -> Dict[str, Any]:
        """
        Get current health status of all services.
        Like checking the dashboard lights before heading out on the road.
        
        Returns:
            Dictionary with service health information
        """
        now = timezone.now()
        health_status = {}
        
        for service, breaker in self._circuit_breakers.items():
            status = {
                'state': breaker['state'],
                'failure_count': breaker['failure_count'],
                'last_failure': breaker['last_failure'].isoformat() if breaker['last_failure'] else None,
                'healthy': breaker['state'] == 'closed' and breaker['failure_count'] < 3
            }
            
            if breaker['state'] == 'open':
                status['next_attempt'] = breaker['next_attempt'].isoformat()
                status['cooldown_remaining'] = max(0, (breaker['next_attempt'] - now).total_seconds())
            
            health_status[service] = status
        
        return health_status


class ContextPreservationService:
    """
    Service for preserving context during error recovery and retries.
    Like keeping track of what you were doing when the truck broke down.
    """
    
    def __init__(self):
        """Initialize context preservation service."""
        self.logger = logging.getLogger(__name__)
    
    def save_processing_context(self, document_id: int, processing_session: str,
                              context_data: Dict[str, Any]) -> str:
        """
        Save processing context for potential retry operations.
        Like writing down exactly what was happening when things went sideways.
        
        Args:
            document_id: ID of the document being processed
            processing_session: Unique session identifier
            context_data: Processing context to preserve
            
        Returns:
            Context key for retrieval
        """
        context_key = f"ctx_{document_id}_{processing_session}"
        
        # Store context in cache/database for retry operations
        from django.core.cache import cache
        
        preserved_context = {
            'document_id': document_id,
            'processing_session': processing_session,
            'timestamp': timezone.now().isoformat(),
            'context_data': context_data,
            'attempt_history': []
        }
        
        # Store for 24 hours (enough time for manual intervention if needed)
        cache.set(context_key, preserved_context, timeout=86400)
        
        self.logger.debug(f"Preserved processing context for document {document_id}")
        return context_key
    
    def retrieve_processing_context(self, context_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve preserved processing context.
        Like checking your notes to remember where you left off.
        
        Args:
            context_key: Key for the preserved context
            
        Returns:
            Preserved context data or None if not found
        """
        from django.core.cache import cache
        
        context = cache.get(context_key)
        if context:
            self.logger.debug(f"Retrieved processing context: {context_key}")
            return context
        else:
            self.logger.warning(f"Processing context not found: {context_key}")
            return None
    
    def add_attempt_to_context(self, context_key: str, attempt_info: Dict[str, Any]):
        """
        Add attempt information to preserved context.
        Like adding another entry to your repair log.
        
        Args:
            context_key: Key for the preserved context
            attempt_info: Information about the attempt
        """
        from django.core.cache import cache
        
        context = cache.get(context_key)
        if context:
            context['attempt_history'].append({
                'timestamp': timezone.now().isoformat(),
                'attempt_info': attempt_info
            })
            
            # Extend timeout on activity
            cache.set(context_key, context, timeout=86400)
            self.logger.debug(f"Added attempt info to context: {context_key}")


# Global instances for easy access
error_recovery_service = ErrorRecoveryService()
context_preservation_service = ContextPreservationService() 