import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { PeriodProvider } from "@/contexts/PeriodContext";
import { ReportingModeProvider } from "@/contexts/ReportingModeContext";
import { FilterProvider } from "@/contexts/FilterContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Audit from "./pages/Audit";
import Chargebacks from "./pages/Chargebacks";
import PnL from "./pages/PnL";
import Redistribution from "./pages/Redistribution";
import PnLReconciliation from "./pages/PnLReconciliation";
import Reconciliation4Way from "./pages/Reconciliation4Way";
import ReconciliationAuto from "./pages/ReconciliationAuto";
import Warehouse from "./pages/Warehouse";
import Taxes from "./pages/Taxes";
import Supplies from "./pages/Supplies";
import Units from "./pages/Units";
import ProductPage from "./pages/ProductPage";
import Funnel from "./pages/Funnel";
import UnitPlan from "./pages/UnitPlan";
import Tariffs from "./pages/Tariffs";
import DimensionsHistory from "./pages/DimensionsHistory";
import Settings from "./pages/Settings";
import RevenueCorrections from "./pages/RevenueCorrections";
import AdsHeatmap from "./pages/AdsHeatmap";
import PaymentCalendar from "./pages/PaymentCalendar";
import Notifications from "./pages/Notifications";
import ExternalMarketing from "./pages/ExternalMarketing";
import Opex from "./pages/Opex";
import CostHistory from "./pages/CostHistory";
import AbcAnalysis from "./pages/AbcAnalysis";
import Supply from "./pages/Supply";
import Plans from "./pages/Plans";
import CashFlow from "./pages/CashFlow";
import UnitCalculator from "./pages/UnitCalculator";
import OffPlatformStock from "./pages/OffPlatformStock";
import Inventory from "./pages/Inventory";
import ProductGroups from "./pages/ProductGroups";
import AuditLog from "./pages/AuditLog";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Legal from "./pages/Legal";
import BoxDistribution from "./pages/BoxDistribution";
import Users from "./pages/Users";
import Brands from "./pages/Brands";
import Glossary from "./pages/Glossary";
import Docs from "./pages/Docs";
import DocPage from "./pages/DocPage";
import Features from "./pages/Features";
import Checklist from "./pages/Checklist";
import SeasonPlan from "./pages/SeasonPlan";
import Jam from "./pages/Jam";
import Localization from "./pages/Localization";
import NewProducts from "./pages/NewProducts";
import TransitCalculator from "./pages/TransitCalculator";
import SupplyCalculator from "./pages/SupplyCalculator";
import WeeklyReport from "./pages/WeeklyReport";
import ManagerSummary from "./pages/ManagerSummary";
import AbTestList from "./pages/AbTestList";
import AbTestNew from "./pages/AbTestNew";
import AbTestDetail from "./pages/AbTestDetail";
import ManagersKpi from "./pages/ManagersKpi";
import PromoCalculator from "./pages/PromoCalculator";
import PromoCalculatorWb from "./pages/PromoCalculatorWb";
import PromoMargin from "./pages/PromoMargin";
import LeakReport from "./pages/LeakReport";
import SummaryReport from "./pages/SummaryReport";
import Stocks from "./pages/Stocks";
import Deductions from "./pages/Deductions";
import Operations from "./pages/Operations";
import AdCampaignsAnalytics from "./pages/AdCampaignsAnalytics";
import BusinessSummary from "./pages/BusinessSummary";
import FinanceExtras from "./pages/FinanceExtras";
import RnpModule from "./pages/RnpModule";
import RnpSettings from "./pages/RnpSettings";
import Files from "./pages/Files";
import DataRevisions from "./pages/DataRevisions";
import CashflowCalendar from "./pages/CashflowCalendar";
import MetricPlanFact from "./pages/MetricPlanFact";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading, needsBootstrap } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-muted">
        Загрузка…
      </div>
    );
  }
  if (!user || needsBootstrap) {
    return (
      <Navigate
        to="/login"
        state={{ from: location.pathname + location.search }}
        replace
      />
    );
  }
  return <>{children}</>;
}

function DirectorOnly({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "director") {
    return (
      <div className="card text-warn">
        Эта страница доступна только пользователю с ролью <code>director</code>.
      </div>
    );
  }
  return <>{children}</>;
}

function DirectorOrHead({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "director" && user?.role !== "head_of_sales") {
    return (
      <div className="card text-warn">
        Доступ только для ролей <code>director</code> и{" "}
        <code>head_of_sales</code>.
      </div>
    );
  }
  return <>{children}</>;
}

// TASK-DEV-096: /truestats — включает UX-профиль меню «TrueStats» (только
// разделы, эквивалентные TS) и ведёт на дашборд. Hard-reload, чтобы Layout
// перечитал профиль из localStorage.
function TruestatsEntry() {
  useEffect(() => {
    try { localStorage.setItem("sidebar.profile.v1", "truestats"); } catch {}
    window.location.replace("/");
  }, []);
  return null;
}

export default function App() {
  return (
    <AuthProvider>
      <PeriodProvider>
      <ReportingModeProvider>
      <FilterProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/legal" element={<Legal />} />
        {/* DEV-091: мобильный сканер раскладки — полноэкранный, без сайдбара */}
        <Route
          path="/box-scan"
          element={
            <ProtectedRoute>
              <BoxDistribution />
            </ProtectedRoute>
          }
        />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="pnl" element={<PnL />} />
          <Route path="summary-report" element={<SummaryReport />} />
          <Route path="deductions" element={<DirectorOrHead><Deductions /></DirectorOrHead>} />
          <Route path="operations" element={<DirectorOrHead><Operations /></DirectorOrHead>} />
          <Route path="stocks" element={<DirectorOrHead><Stocks /></DirectorOrHead>} />
          <Route path="ad-campaigns" element={<DirectorOrHead><AdCampaignsAnalytics /></DirectorOrHead>} />
          <Route path="business-summary" element={<DirectorOrHead><BusinessSummary /></DirectorOrHead>} />
          <Route path="finance-extras" element={<DirectorOrHead><FinanceExtras /></DirectorOrHead>} />
          <Route path="rnp-module" element={<RnpModule />} />
          <Route path="rnp-settings" element={<DirectorOrHead><RnpSettings /></DirectorOrHead>} />
          <Route path="files" element={<DirectorOrHead><Files /></DirectorOrHead>} />
          <Route path="data-revisions" element={<DirectorOrHead><DataRevisions /></DirectorOrHead>} />
          <Route path="truestats" element={<TruestatsEntry />} />
          <Route path="cashflow-calendar" element={<DirectorOrHead><CashflowCalendar /></DirectorOrHead>} />
          <Route path="metric-plan-fact" element={<DirectorOrHead><MetricPlanFact /></DirectorOrHead>} />
          <Route path="pnl-reconciliation" element={<PnLReconciliation />} />
          <Route
            path="reconciliation-4way"
            element={
              <DirectorOrHead>
                <Reconciliation4Way />
              </DirectorOrHead>
            }
          />
          <Route path="reconciliation-auto" element={<ReconciliationAuto />} />
          <Route path="warehouse" element={<DirectorOrHead><Warehouse /></DirectorOrHead>} />
          <Route
            path="audit"
            element={
              <DirectorOrHead>
                <Audit />
              </DirectorOrHead>
            }
          />
          <Route path="chargebacks" element={<Chargebacks />} />
          <Route
            path="leak-report"
            element={
              <DirectorOrHead>
                <LeakReport />
              </DirectorOrHead>
            }
          />
          <Route
            path="managers-kpi"
            element={
              <DirectorOrHead>
                <ManagersKpi />
              </DirectorOrHead>
            }
          />
          <Route path="redistribution" element={<Redistribution />} />
          {/* TASK-LEAD-041: единая страница `/taxes` с табами. Старые URL */}
          {/* делают back-compat redirect на `/taxes?mode=X` — для bookmark'ов. */}
          <Route path="taxes" element={<Taxes />} />
          <Route
            path="tax-report"
            element={<Navigate to="/taxes?mode=base" replace />}
          />
          <Route
            path="tax-report-ausn"
            element={<Navigate to="/taxes?mode=ausn" replace />}
          />
          <Route
            path="tax-report-usn"
            element={<Navigate to="/taxes?mode=usn" replace />}
          />
          <Route
            path="tax-report-usn-vat5"
            element={<Navigate to="/taxes?mode=usn-vat5" replace />}
          />
          <Route
            path="tax-report-usn-vat7"
            element={<Navigate to="/taxes?mode=usn-vat7" replace />}
          />
          <Route
            path="supplies"
            element={
              <DirectorOrHead>
                <Supplies />
              </DirectorOrHead>
            }
          />
          <Route path="units" element={<Units />} />
          <Route path="product/:nmId" element={<ProductPage />} />
          <Route path="funnel" element={<Funnel />} />
          <Route path="unit-plan" element={<UnitPlan />} />
          <Route path="tariffs" element={<Tariffs />} />
          <Route path="dimensions-history" element={<DimensionsHistory />} />
          <Route
            path="revenue-corrections"
            element={
              <DirectorOrHead>
                <RevenueCorrections />
              </DirectorOrHead>
            }
          />
          <Route
            path="external-marketing"
            element={
              <DirectorOrHead>
                <ExternalMarketing />
              </DirectorOrHead>
            }
          />
          <Route path="ads-heatmap" element={<AdsHeatmap />} />
          <Route
            path="notifications"
            element={
              <DirectorOrHead>
                <Notifications />
              </DirectorOrHead>
            }
          />
          <Route
            path="payment-calendar"
            element={
              <DirectorOrHead>
                <PaymentCalendar />
              </DirectorOrHead>
            }
          />
          <Route
            path="opex"
            element={
              <DirectorOrHead>
                <Opex />
              </DirectorOrHead>
            }
          />
          <Route path="cost-history" element={<CostHistory />} />
          <Route path="abc" element={<AbcAnalysis />} />
          <Route path="supply" element={<Supply />} />
          <Route path="plans" element={<Plans />} />
          <Route
            path="cash-flow"
            element={
              <DirectorOrHead>
                <CashFlow />
              </DirectorOrHead>
            }
          />
          <Route
            path="off-platform"
            element={
              <DirectorOrHead>
                <OffPlatformStock />
              </DirectorOrHead>
            }
          />
          <Route
            path="capitalization"
            element={<Navigate to="/off-platform" replace />}
          />
          <Route path="inventory" element={<Inventory />} />
          <Route path="product-groups" element={<ProductGroups />} />
          <Route
            path="audit-log"
            element={
              <DirectorOnly>
                <AuditLog />
              </DirectorOnly>
            }
          />
          <Route path="calc" element={<UnitCalculator />} />
          <Route path="promo-calculator" element={<PromoCalculator />} />
          <Route path="promo-calculator-wb" element={<PromoCalculatorWb />} />
          <Route path="promo-margin" element={<PromoMargin />} />
          <Route
            path="users"
            element={
              <DirectorOnly>
                <Users />
              </DirectorOnly>
            }
          />
          <Route
            path="brands"
            element={
              <DirectorOrHead>
                <Brands />
              </DirectorOrHead>
            }
          />
          <Route path="glossary" element={<Glossary />} />
          <Route path="docs" element={<Docs />} />
          <Route path="docs/:slug" element={<DocPage />} />
          <Route path="features" element={<Features />} />
          <Route path="checklist" element={<Checklist />} />
          <Route
            path="season-plan"
            element={
              <DirectorOrHead>
                <SeasonPlan />
              </DirectorOrHead>
            }
          />
          <Route path="jam" element={<Jam />} />
          <Route path="localization" element={<Localization />} />
          <Route path="abtest" element={<AbTestList />} />
          <Route path="abtest/new" element={<AbTestNew />} />
          <Route path="abtest/:id" element={<AbTestDetail />} />
          <Route
            path="new-products"
            element={
              <DirectorOrHead>
                <NewProducts />
              </DirectorOrHead>
            }
          />
          {/* TASK-LEAD-077: разделение транзит / обычная поставка */}
          <Route path="supply-calculator" element={<SupplyCalculator />} />
          <Route path="transit-calculator" element={<TransitCalculator />} />
          <Route path="weekly-report" element={<WeeklyReport />} />
          <Route path="manager-summary" element={<ManagerSummary />} />
          <Route
            path="settings"
            element={
              <DirectorOnly>
                <Settings />
              </DirectorOnly>
            }
          />
        </Route>
      </Routes>
      </FilterProvider>
      </ReportingModeProvider>
      </PeriodProvider>
    </AuthProvider>
  );
}
