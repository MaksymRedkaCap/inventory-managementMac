<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrencyWithDecimals } from '../utils/currency'

const { t, currentCurrency, translateProductName } = useI18n()

const forecasts = ref([])
const loading = ref(true)
const error = ref(null)
const budget = ref(0)
const submitting = ref(false)
const submitError = ref(null)
const confirmation = ref(null)

const money = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 2)
const moneyWhole = (amount) => formatCurrencyWithDecimals(amount, currentCurrency.value, 0)

const growth = (f) => (f.current_demand > 0
  ? (f.forecasted_demand - f.current_demand) / f.current_demand
  : 0)

const candidates = computed(() =>
  forecasts.value.filter(f => f.trend !== 'decreasing')
)

// Slider max: cost of restocking every non-decreasing item in full, rounded up to next 1000
const maxBudget = computed(() => {
  const total = candidates.value.reduce((sum, f) => sum + f.forecasted_demand * f.unit_cost, 0)
  return (Math.floor(total / 1000) + 1) * 1000
})

// Greedy fill by growth rate: highest-growth items are funded first at full forecasted
// quantity. The first item that no longer fits is partially filled with whatever whole
// units the remaining budget affords (if at least 1), then we stop so lower-growth
// items are never funded ahead of a higher-growth one.
const recommendations = computed(() => {
  const sorted = [...candidates.value].sort((a, b) => growth(b) - growth(a))
  const result = []
  let remaining = budget.value
  for (const f of sorted) {
    const fullCost = f.forecasted_demand * f.unit_cost
    if (fullCost <= remaining) {
      result.push({ ...f, quantity: f.forecasted_demand, line_cost: fullCost })
      remaining -= fullCost
      continue
    }
    const units = Math.floor(remaining / f.unit_cost)
    if (units >= 1) {
      result.push({ ...f, quantity: units, line_cost: units * f.unit_cost })
    }
    break
  }
  return result
})

const totalSpent = computed(() => recommendations.value.reduce((s, r) => s + r.line_cost, 0))
const budgetRemaining = computed(() => budget.value - totalSpent.value)
const orderLeadTime = computed(() =>
  recommendations.value.reduce((m, r) => Math.max(m, r.lead_time_days), 0)
)

const formatDate = (dateString) => {
  const d = new Date(dateString)
  if (isNaN(d.getTime())) return dateString
  const { currentLocale } = useI18n()
  return d.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
    year: 'numeric', month: 'short', day: 'numeric'
  })
}

const loadData = async () => {
  loading.value = true
  error.value = null
  try {
    forecasts.value = await api.getDemandForecasts()
    budget.value = Math.min(budget.value, maxBudget.value)
  } catch (err) {
    error.value = t('restocking.loadError')
    console.error(err)
  } finally {
    loading.value = false
  }
}

const placeOrder = async () => {
  if (!recommendations.value.length || submitting.value) return
  submitting.value = true
  submitError.value = null
  confirmation.value = null
  try {
    confirmation.value = await api.createRestockingOrder({
      items: recommendations.value.map(r => ({ sku: r.item_sku, quantity: r.quantity }))
    })
  } catch (err) {
    submitError.value = err.response?.data?.detail || err.message || t('restocking.submitError')
    console.error(err)
  } finally {
    submitting.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
          <span class="budget-readout">{{ moneyWhole(budget) }}</span>
        </div>
        <div class="budget-body">
          <input
            v-model.number="budget"
            type="range"
            min="0"
            :max="maxBudget"
            step="1000"
            class="budget-slider"
            :aria-label="t('restocking.budget')"
          />
          <div class="budget-scale">
            <span>{{ moneyWhole(0) }}</span>
            <span>{{ moneyWhole(maxBudget) }}</span>
          </div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.totalSpent') }}</div>
          <div class="stat-value">{{ money(totalSpent) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.budgetRemaining') }}</div>
          <div class="stat-value">{{ money(budgetRemaining) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.orderLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="confirmation" class="notice success-notice" role="status">
        <strong>{{ t('restocking.confirmationTitle') }}</strong>
        <div>{{ t('restocking.orderNumber') }}: {{ confirmation.order_number }}</div>
        <div>{{ t('restocking.orderLeadTime') }}: {{ t('restocking.days', { count: confirmation.lead_time_days }) }}</div>
        <div>{{ t('restocking.expectedDelivery') }}: {{ formatDate(confirmation.expected_delivery) }}</div>
        <router-link to="/orders" class="notice-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="notice error-notice" role="alert">
        {{ t('restocking.submitFailed') }}: {{ submitError }}
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommended') }} ({{ recommendations.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="!recommendations.length || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div v-if="!recommendations.length" class="empty-state">
          {{ t('restocking.empty') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.name') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendations" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td>{{ item.quantity }}</td>
                <td>{{ money(item.unit_cost) }}</td>
                <td><strong>{{ money(item.line_cost) }}</strong></td>
                <td>{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-readout {
  font-size: 1.25rem;
  font-weight: 600;
  color: #0f172a;
}

.budget-body {
  padding: 0.5rem 0 0.25rem;
}

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.notice {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.875rem;
}

.success-notice {
  background: #f0fdf4;
  border-color: #86efac;
  color: #166534;
}

.error-notice {
  background: #fef2f2;
  border-color: #fca5a5;
  color: #991b1b;
}

.notice-link {
  color: #2563eb;
  font-weight: 500;
  margin-top: 0.25rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}
</style>
