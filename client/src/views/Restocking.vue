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
        <div class="budget-header">
          <label class="budget-label" for="budget-slider">{{ t('restocking.budgetLabel') }}</label>
          <span class="budget-value">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
        </div>
        <input
          id="budget-slider"
          type="range"
          class="budget-slider"
          min="0"
          max="200000"
          step="1000"
          v-model.number="budget"
          @change="loadRecommendations"
        >
      </div>

      <div v-if="successMessage" class="success-banner">{{ successMessage }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
          <button
            class="btn-primary"
            :disabled="selectedItems.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div class="totals-row">
          <div class="totals-item">
            <span class="totals-label">{{ t('restocking.totalCost') }}</span>
            <span class="totals-value">{{ currencySymbol }}{{ selectedTotal.toLocaleString() }}</span>
          </div>
          <div class="totals-item">
            <span class="totals-label">{{ t('restocking.remainingBudget') }}</span>
            <span class="totals-value" :class="{ negative: remainingBudget < 0 }">
              {{ currencySymbol }}{{ remainingBudget.toLocaleString() }}
            </span>
          </div>
        </div>

        <div v-if="budgetTooLow" class="notice">{{ t('restocking.budgetTooLow') }}</div>

        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantityOnHand') }}</th>
                <th>{{ t('restocking.table.forecastedDemand') }}</th>
                <th>{{ t('restocking.table.restockQuantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.restockCost') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in recommendations"
                :key="item.item_sku"
                :class="{ muted: !item.has_inventory_match || item.restock_quantity === 0 }"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="checkedSkus[item.item_sku]"
                    @change="toggleSku(item.item_sku)"
                    :disabled="!item.has_inventory_match || item.restock_quantity === 0"
                  >
                </td>
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>
                  {{ translateProductName(item.item_name) }}
                  <div v-if="!item.has_inventory_match" class="row-note">{{ t('restocking.noInventoryData') }}</div>
                  <div v-else-if="item.restock_quantity === 0" class="row-note">{{ t('restocking.demandMet') }}</div>
                </td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td>{{ item.quantity_on_hand }}</td>
                <td>{{ item.forecasted_demand }}</td>
                <td><strong>{{ item.restock_quantity }}</strong></td>
                <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                <td>{{ currencySymbol }}{{ item.restock_cost.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successMessage = ref(null)

    const budget = ref(50000)
    const recommendationsData = ref(null)
    const checkedSkus = reactive({})

    const recommendations = computed(() => {
      return recommendationsData.value ? recommendationsData.value.recommendations : []
    })

    const budgetTooLow = computed(() => {
      return budget.value > 0 &&
        recommendations.value.length > 0 &&
        !recommendations.value.some(item => item.recommended === true)
    })

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        const data = await api.getRestockingRecommendations(budget.value)
        recommendationsData.value = data

        // Reset checked state from fresh fetch only
        Object.keys(checkedSkus).forEach(key => delete checkedSkus[key])
        data.recommendations.forEach(item => {
          checkedSkus[item.item_sku] = !!item.recommended
        })
      } catch (err) {
        error.value = 'Failed to load restocking recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const toggleSku = (sku) => {
      checkedSkus[sku] = !checkedSkus[sku]
    }

    const selectedItems = computed(() => {
      return recommendations.value.filter(item =>
        checkedSkus[item.item_sku] && item.has_inventory_match && item.restock_quantity > 0
      )
    })

    const selectedTotal = computed(() => {
      return selectedItems.value.reduce((sum, item) => sum + item.restock_cost, 0)
    })

    const remainingBudget = computed(() => {
      return budget.value - selectedTotal.value
    })

    const placeOrder = async () => {
      try {
        submitting.value = true
        error.value = null
        successMessage.value = null

        const items = selectedItems.value.map(item => ({
          item_sku: item.item_sku,
          item_name: item.item_name,
          quantity: item.restock_quantity,
          unit_cost: item.unit_cost
        }))

        const result = await api.createRestockingOrder({ items, budget: budget.value })
        successMessage.value = t('restocking.orderSuccess', { orderNumber: result.order_number })

        await loadRecommendations()
      } catch (err) {
        error.value = 'Failed to place restocking order: ' + err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      loading,
      error,
      submitting,
      successMessage,
      budget,
      recommendations,
      checkedSkus,
      toggleSku,
      selectedItems,
      selectedTotal,
      remainingBudget,
      budgetTooLow,
      loadRecommendations,
      placeOrder,
      currencySymbol,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
  outline: none;
  -webkit-appearance: none;
  appearance: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 3px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.15s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: 3px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.15s ease;
}

.budget-slider::-moz-range-thumb:hover {
  transform: scale(1.1);
}

.budget-slider::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: #e2e8f0;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.totals-row {
  display: flex;
  gap: 2rem;
  margin-bottom: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #f1f5f9;
}

.totals-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.totals-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.totals-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.totals-value.negative {
  color: #dc2626;
}

.notice {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #92400e;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

tbody tr.muted {
  opacity: 0.5;
}

.row-note {
  font-size: 0.75rem;
  color: #94a3b8;
  font-style: italic;
  margin-top: 0.125rem;
}

.btn-primary {
  padding: 0.625rem 1.25rem;
  background: #2563eb;
  border: 1px solid #2563eb;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.875rem;
  color: white;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1d4ed8;
}

.btn-primary:disabled {
  background: #94a3b8;
  border-color: #94a3b8;
  cursor: not-allowed;
}
</style>
