/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { BarcodeService } from "../barcode_service";

export class PerformanceScreen extends Component {
    static template = xml`
        <div class="ub-screen">
            <div class="ub-screen-header">
                <button class="btn ub-btn-back" t-on-click="() => this.props.navigate('main')">
                    <i class="fa fa-arrow-left"></i>
                </button>
                <h2 class="ub-screen-title">
                    <i class="fa fa-trophy"></i> Operatör Performans
                </h2>
            </div>

            <!-- DÖNEM SEÇİMİ -->
            <div class="ub-filter-bar">
                <div class="ub-filter-row">
                    <div class="ub-filter-field" style="flex:1">
                        <label class="ub-field-label">Dönem</label>
                        <select class="form-control ub-select" t-on-change="onDaysChange">
                            <option value="1">Bugün</option>
                            <option value="3">Son 3 Gün</option>
                            <option value="7" selected="">Son 7 Gün</option>
                            <option value="14">Son 14 Gün</option>
                            <option value="30">Son 30 Gün</option>
                        </select>
                    </div>
                    <div class="ub-filter-field">
                        <label class="ub-field-label" style="visibility: hidden;">Y</label>
                        <button class="btn btn-primary w-100" t-on-click="loadPerformance" style="height:42px;">
                            <i class="fa fa-refresh"></i>
                        </button>
                    </div>
                </div>
            </div>

            <t t-if="state.loading">
                <div class="ub-loading">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p>Yükleniyor...</p>
                </div>
            </t>

            <t t-if="state.error">
                <div class="ub-error-card">
                    <i class="fa fa-exclamation-triangle"></i>
                    <p t-esc="state.error"/>
                </div>
            </t>

            <t t-if="state.result">
                <!-- GENEL İSTATİSTİK -->
                <div class="ub-perf-total">
                    <div class="ub-perf-big-number" t-esc="state.result.total_operations"/>
                    <div class="ub-perf-big-label">
                        Toplam İşlem (Son <t t-esc="state.result.period_days"/> Gün)
                    </div>
                </div>

                <!-- İŞLEM TÜRÜ DAĞILIMI -->
                <t t-if="Object.keys(state.result.type_totals).length">
                    <div class="ub-perf-section">
                        <h4 class="ub-section-title">
                            <i class="fa fa-pie-chart"></i> İşlem Türü Dağılımı
                        </h4>
                        <div class="ub-type-bars">
                            <t t-foreach="Object.entries(state.result.type_totals)" t-as="entry" t-key="entry[0]">
                                <div class="ub-type-bar-item">
                                    <div class="ub-type-bar-label">
                                        <span t-esc="entry[0]"/>
                                        <span class="ub-type-bar-count" t-esc="entry[1]"/>
                                    </div>
                                    <div class="ub-type-bar-track">
                                        <div class="ub-type-bar-fill"
                                             t-attf-style="width: {{Math.round(entry[1] / state.result.total_operations * 100)}}%"/>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>

                <!-- OPERATÖR LİSTESİ -->
                <t t-if="state.result.operators.length">
                    <div class="ub-perf-section">
                        <h4 class="ub-section-title">
                            <i class="fa fa-users"></i> Operatörler
                        </h4>
                        <t t-foreach="state.result.operators" t-as="op" t-key="op.user_id">
                            <div class="ub-operator-card">
                                <div class="ub-op-rank">
                                    <span t-attf-class="ub-rank-badge {{op_index === 0 ? 'ub-rank-gold' : op_index === 1 ? 'ub-rank-silver' : op_index === 2 ? 'ub-rank-bronze' : ''}}"
                                          t-esc="op_index + 1"/>
                                </div>
                                <div class="ub-op-info">
                                    <div class="ub-op-name" t-esc="op.user_name"/>
                                    <div class="ub-op-meta">
                                        Son: <span t-esc="op.last_activity"/>
                                    </div>
                                    <div class="ub-op-types">
                                        <t t-foreach="Object.entries(op.types)" t-as="t_entry" t-key="t_entry[0]">
                                            <span class="badge bg-light text-dark me-1 mb-1">
                                                <t t-esc="t_entry[0]"/>: <t t-esc="t_entry[1]"/>
                                            </span>
                                        </t>
                                    </div>
                                </div>
                                <div class="ub-op-total">
                                    <span class="ub-op-total-num" t-esc="op.total"/>
                                    <span class="ub-op-total-label">işlem</span>
                                </div>
                            </div>
                        </t>
                    </div>
                </t>

                <div class="ub-no-stock" t-if="!state.result.operators.length">
                    <i class="fa fa-inbox"></i>
                    <p>Bu dönemde işlem bulunamadı</p>
                </div>
            </t>
        </div>
    `;

    static props = { navigate: Function, scanner: Object };

    setup() {
        this.state = useState({
            days: 7,
            loading: false,
            error: null,
            result: null,
        });
        this.loadPerformance();
    }

    onDaysChange(ev) { this.state.days = ev.target.value; }

    async loadPerformance() {
        this.state.loading = true;
        this.state.error = null;
        this.state.result = null;
        try {
            const result = await BarcodeService.operatorPerformance(this.state.days);
            if (result.error) this.state.error = result.error;
            else this.state.result = result;
        } catch (e) {
            this.state.error = 'Hata: ' + (e.message || e);
        }
        this.state.loading = false;
    }
}
