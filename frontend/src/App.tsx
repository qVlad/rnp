import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { PeriodProvider } from "@/contexts/PeriodContext";
import { ReportingModeProvider } from "@/contexts/ReportingModeContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Audit from "./pages/Audit";
import Chargebacks from "./pages/Chargebacks";
import PnL from "./pages/PnL";
import Redistribution from "./pages/Redistribution";
import PnLReconciliation from "./pages/PnLReconciliation";
import Reconciliation4Way from "./pages/Reconciliation4Way";
import Taxes from "./pages/Taxes";
import Supplies from "./pages/Supplies";
import Units from "./pages/Units";
import Funnel from "./pages/Funnel";
import UnitPlan from "./pages/UnitPlan";
import Tariffs from "./pages/Tariffs";
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
import Users from "./pages/Users";
import Brands from "./pages/Brands";
import Glossary from "./pages/Glossary";
import Docs from "./pages/Docs";
import Features from "./pages/Features";
import Checklist from "./pages/Checklist";
import SeasonPlan from "./pages/SeasonPlan";
import Jam from "./pages/Jam";
import Localization from "./pages/Localization";
import NewProducts from "./pages/NewProducts";
import TransitCalculator from "./pages/TransitCalculator";
import SupplyCalculator from "./pages/SupplyCalculator";
import WeeklyReport from "./pages/WeeklyReport";
import AbTestList from "./pages/AbTestList";
import AbTestNew from "./pages/AbTestNew";
import AbTestDetail from "./pages/AbTestDetail";
import ManagersKpi from "./pages/ManagersKpi";
import PromoCalculator from "./pages/PromoCalculator";

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

export default function App() {
  return (
    <AuthProvider>
      <PeriodProvider>
      <ReportingModeProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/legal" element={<Legal />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="pnl" element={<PnL />} />
          <Route path="pnl-reconciliation" element={<PnLReconciliation />} />
          <Route
            path="reconciliation-4way"
            element={
              <DirectorOrHead>
                <Reconciliation4Way />
              </DirectorOrHead>
            }
          />
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
          <Route path="funnel" element={<Funnel />} />
          <Route path="unit-plan" element={<UnitPlan />} />
          <Route path="tariffs" element={<Tariffs />} />
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
      </ReportingModeProvider>
      </PeriodProvider>
    </AuthProvider>
  );
}
