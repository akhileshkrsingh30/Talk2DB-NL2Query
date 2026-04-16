# ERP System Database Architecture

This is a structural breakdown of the newly synchronized `erp_system` database.

## Schema Summary

| Schema Name | Total Tables |
|---|---|
| inventory | 106 |
| hr | 98 |
| finance | 88 |
| manufacturing | 77 |
| sales | 68 |
| rnd | 20 |
| quality | 15 |
| logistics | 9 |
| public | 6 |

**Total Tables across all schemas:** 487

---

## Table Listing by Primary Schemas

### Schema: `inventory` (106 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `abc_classification` | `ai_forecast_result` | `asn` |
| `asn_item` | `barcode_scan` | `batch` |
| `batch_trace` | `bin` | `bin_audit` |
| `bin_occupancy` | `bin_restriction` | `bin_stock` |
| `bin_transfer` | `capa` | `carrier_handover` |
| `consumption_history` | `cycle_count_bin` | `cycle_count_result` |
| `cycle_count_schedule` | `defect_code` | `dispatch_order` |
| `dispatch_package` | `echelon_stock` | `environment_reading` |
| `environment_zone` | `forecast` | `forecast_override` |
| `forecast_version` | `fsn_xyz` | `grn` |
| `grn_item` | `inspection_characteristic` | `inspection_lot` |
| `inspection_result` | `inventory_aging` | `inventory_ledger` |
| `inventory_optimization` | `item` | `item_attribute` |
| `item_attribute_value` | `item_category` | `item_genealogy` |
| `item_group` | `item_velocity` | `lead_time_history` |
| `loading_dock` | `loading_plan` | `loading_plan_detail` |
| `material_issue_item` | `material_issue_request` | `material_return` |
| `material_return_item` | `movement_type` | `ncr` |
| `network_node` | `package` | `package_item` |
| `packing_session` | `packing_station` | `pick_confirmation` |
| `pick_task` | `pick_task_item` | `picking_wave` |
| `purchase_order` | `purchase_order_item` | `purchase_requisition` |
| `purchase_requisition_item` | `putaway_event` | `putaway_rule` |
| `putaway_task` | `qc_defect` | `qc_inspection` |
| `qc_inspection_result` | `qc_metric` | `qc_metric_value` |
| `qc_plan` | `qc_plan_step` | `quality_hold` |
| `quality_release` | `reorder_policy` | `replenishment_policy` |
| `reservation_release` | `rfid_scan` | `rfid_tag` |
| `safety_stock_calc` | `sampling_procedure` | `serial_number` |
| `shelf_life_risk` | `shipping_manifest` | `slotting_strategy` |
| `stock_adjustment` | `stock_adjustment_item` | `stock_reservation` |
| `supplier` | `supplier_delivery_performance` | `supplier_item` |
| `supplier_risk` | `supplier_scorecard` | `transfer_request` |
| `transfer_request_item` | `transfer_shipment` | `transfer_shipment_item` |
| `uom` | `warehouse` | `wave_order` |
| `zone` | `` | `` |

### Schema: `hr` (98 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `absence_report` | `applicant` | `application` |
| `application_screening` | `assessment_test` | `attendance_record` |
| `background_check` | `benefit` | `bonus_head` |
| `calibration_committee` | `candidate_assessment` | `candidate_profile` |
| `committee_member` | `competency` | `cost_center` |
| `department` | `disciplinary_action` | `disciplinary_case` |
| `employee` | `employee_benefit` | `employee_bonus` |
| `employee_certification` | `employee_competency_rating` | `employee_component_override` |
| `employee_cost_center` | `employee_goal` | `employee_overtime` |
| `employee_position_history` | `employee_salary_structure` | `employee_skill` |
| `employment_contract` | `feedback_response` | `feedback_reviewer` |
| `final_rating` | `goal_template` | `goal_template_item` |
| `grievance` | `grievance_resolution` | `hr_audit` |
| `hr_audit_finding` | `hr_metric` | `hr_metric_value` |
| `hr_policy` | `hr_risk` | `interview_feedback` |
| `interview_panel` | `interview_panel_member` | `interview_round` |
| `interview_schedule` | `job_application` | `job_grade` |
| `job_offer` | `job_posting` | `job_requisition` |
| `kpi` | `learning_path` | `learning_path_course` |
| `leave_request` | `leave_type` | `manager_assessment` |
| `overtime_policy` | `payroll_audit_log` | `payroll_calendar` |
| `payroll_cycle` | `payroll_entry` | `payroll_entry_line` |
| `payroll_export_queue` | `payroll_gl_mapping` | `payroll_item` |
| `payroll_period` | `payroll_period_type` | `payroll_run` |
| `payroll_run_line` | `performance_cycle` | `performance_history` |
| `policy_violation` | `position` | `recruitment_summary` |
| `requisition_approval_step` | `salary_component` | `salary_structure` |
| `salary_structure_group` | `self_assessment` | `skill` |
| `social_security_config` | `structure_component` | `survey` |
| `survey_question` | `survey_response` | `tax_slab` |
| `trainer` | `training_attendance` | `training_category` |
| `training_compliance_audit` | `training_course` | `training_enrollment` |
| `training_session` | `workforce_plan` | `` |

### Schema: `finance` (88 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `account_group` | `ap_aging` | `ap_credit_memo` |
| `ap_debit_memo` | `ap_gl_posting` | `ap_invoice` |
| `ap_invoice_line` | `ap_matching` | `ap_matching_line` |
| `ap_payment` | `ap_payment_application` | `ap_payment_proposal` |
| `ap_payment_proposal_item` | `ap_statement` | `ap_vendor` |
| `ap_vendor_contact` | `ap_withholding` | `ar_adjustment` |
| `ar_aging` | `ar_contact` | `ar_credit_adjustment` |
| `ar_credit_hold` | `ar_customer` | `ar_dunning` |
| `ar_gl_posting` | `ar_invoice` | `ar_invoice_line` |
| `ar_lockbox_file` | `ar_lockbox_payment` | `ar_receipt` |
| `ar_receipt_application` | `ar_writeoff` | `asset` |
| `asset_category` | `asset_class` | `asset_depreciation` |
| `asset_disposal` | `asset_gl_posting` | `asset_impairment` |
| `asset_insurance` | `asset_revaluation` | `asset_transfer` |
| `asset_verification` | `bank` | `bank_account` |
| `bank_branch` | `bank_gl_posting` | `bank_reconciliation` |
| `bank_reconciliation_item` | `bank_statement` | `bank_statement_line` |
| `bank_transaction` | `bank_transfer` | `cash_forecast` |
| `cash_position` | `cheque` | `cip_cost` |
| `cip_project` | `cost_center` | `depreciation_area` |
| `depreciation_line` | `depreciation_method` | `depreciation_run` |
| `exchange_rate` | `exchange_rate_type` | `fin_dimension` |
| `fin_dimension_value` | `fiscal_period` | `fiscal_year` |
| `gl_account` | `journal` | `journal_line` |
| `profit_center` | `tax_authority` | `tax_calculation` |
| `tax_calculation_line` | `tax_category` | `tax_code` |
| `tax_exemption` | `tax_gl_posting` | `tax_jurisdiction` |
| `tax_rate` | `tax_return` | `tax_return_line` |
| `tax_rule` | `tax_type` | `withholding_rule` |
| `withholding_type` | `` | `` |

### Schema: `manufacturing` (77 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `andon_event` | `batch_consumption` | `bom` |
| `bom_component` | `bottleneck` | `capacity_load` |
| `capacity_master` | `capacity_requirement` | `capacity_scenario` |
| `capacity_scenario_detail` | `condition_parameter` | `condition_reading` |
| `cost_variance` | `downtime_pareto` | `downtime_reason` |
| `employee_skill` | `first_pass_yield` | `ipqc_check` |
| `labor_allocation` | `labor_efficiency` | `labor_time` |
| `lead_time` | `machine` | `machine_allocation` |
| `machine_capability` | `machine_downtime` | `machine_efficiency` |
| `machine_reliability` | `machine_run` | `maintenance_cost` |
| `maintenance_plan` | `maintenance_spare` | `maintenance_strategy` |
| `maintenance_task` | `maintenance_type` | `maintenance_work_order` |
| `material_issue` | `material_issue_line` | `material_variance` |
| `mfg_daily_fact` | `mfg_gl_posting` | `mfg_kpi` |
| `mfg_kpi_value` | `oee` | `oee_loss` |
| `operation_confirmation` | `operation_execution` | `operator_skill` |
| `planned_order` | `plant` | `predictive_alert` |
| `production_confirmation` | `production_cost` | `production_line` |
| `production_order` | `production_order_operation` | `production_yield` |
| `rework_analytics` | `rework_execution` | `rework_order` |
| `routing` | `routing_operation` | `scrap_analytics` |
| `scrap_material` | `scrap_record` | `serial_consumption` |
| `shift` | `shift_calendar` | `shift_capacity` |
| `shift_production` | `throughput` | `tpm_metric` |
| `tpm_metric_value` | `wip` | `wip_cost` |
| `wip_settlement` | `work_center` | `` |

### Schema: `sales` (68 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `activity` | `attachment` | `billing_account` |
| `campaign_audience` | `campaign_channel` | `campaign_send_log` |
| `carrier` | `contact` | `coupon` |
| `coupon_template` | `credit_note` | `customer` |
| `customer_portal_session` | `customer_portal_user` | `debit_note` |
| `delivery_confirmation` | `dunning_notice` | `finance_posting` |
| `fulfillment_queue` | `interaction` | `invoice` |
| `invoice_item` | `lead` | `lead_score_event` |
| `lead_score_rule` | `lead_score_total` | `loyalty_account` |
| `loyalty_tier` | `loyalty_transaction` | `marketing_campaign` |
| `marketing_template` | `note` | `opportunity` |
| `packing_list` | `packing_list_item` | `payment` |
| `payment_term` | `picking_slip` | `picking_slip_item` |
| `price_list` | `price_list_item` | `product` |
| `promotion` | `promotion_usage` | `quotation` |
| `quotation_item` | `return_inspection` | `return_item` |
| `return_request` | `return_resolution` | `revenue_schedule` |
| `sales_order` | `sales_order_item` | `sales_rep` |
| `sales_territory` | `shipment` | `shipment_event` |
| `sla_contract` | `sla_violation` | `subscription` |
| `subscription_invoice` | `subscription_product` | `tax_code` |
| `usage_record` | `voucher` | `voucher_campaign` |
| `wallet` | `wallet_transaction` | `` |

### Schema: `rnd` (20 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `dataset_lineage` | `experiment` | `experiment_material` |
| `experiment_result` | `experiment_trial` | `graph_measurement` |
| `graph_run` | `graph_signal_event` | `intellectual_property` |
| `program` | `project` | `project_assignment` |
| `publication` | `research_dataset` | `research_expense` |
| `research_team` | `run_observation` | `stage_gate` |
| `team_member` | `trial_run` | `` |

### Schema: `quality` (15 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `audit_finding` | `calibration_equipment` | `calibration_log` |
| `capa` | `customer_complaint` | `inspection_lot` |
| `inspection_plan` | `inspection_plan_characteristic` | `inspection_result` |
| `inspection_type` | `non_conformance` | `quality_audit` |
| `quality_characteristic` | `spc_measurement` | `supplier_quality` |

### Schema: `logistics` (9 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `delivery_confirmation` | `driver` | `freight_cost` |
| `hub` | `route` | `shipment` |
| `shipment_tracking` | `transport_order` | `vehicle` |

### Schema: `public` (6 tables)

| Table Name | Table Name | Table Name |
|---|---|---|
| `company` | `country` | `currency` |
| `role` | `user_account` | `user_role` |

