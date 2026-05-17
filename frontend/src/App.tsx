import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { PeriodProvider } from "@/contexts/PeriodContext";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import PnL from "./pages/PnL";
import PnLReconciliation from "./pages/PnLReconciliation";
import TaxReport from "./pages/TaxReport";
import TaxReportAusn from "./pages/TaxReportAusn";
import Supplies from "./pages/Supplies";
import Units from "./pages/Units";
import Settings from "./pages/Settings";
import RevenueCorrections from "./pages/RevenueCorrections";
import AdsHeatmap from "./pages/AdsHeatmap";
import PaymentCalendar from "./pages/PaymentCalendar";
import TaxReportUsn, { TaxReportUsnVat5, TaxReportUsnVat7 } from "./pages/TaxReportUsn";
import Notifications from "./pages/Notifications";
import ExternalMarketing from "./pages/ExternalMarketing";
import Opex from "./pages/Opex";
import CostHistory from "./pages/CostHistory";
import AbcAnalysis from "./pages/AbcAnalysis";
import Supply from "./pages/Supply";
import Plans from "./pages/Plans";
import CashFlow from "./pages/CashFlow";
import UnitCalculator from "./pages/UnitCalculator";
import Capitalization from "./pages/Capitalization";
import ProductGroups from "./pages/ProductGroups";
import AuditLog from "./pages/AuditLog";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import Legal from "./pages/Legal";
import Users from "./pages/Users";
import Brands from "./pages/Brands";
import Glossary from "./pages/Glossary";
import Docs from "./pages/Docs";
import Checklist from "./pages/Checklist";
import SeasonPlan from "./pages/SeasonPlan";
import Jam from "./pages/Jam";
import NewProducts from "./pages/NewProducts";
import AbTestList from "./pages/AbTestList";
import AbTestNew from "./pages/AbTestNew";
import AbTestDetail from "./pages/AbTestDetail";

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
            path="tax-report"
            element={
              <DirectorOrHead>
                <TaxReport />
              </DirectorOrHead>
            }
          />
          <Route
            path="tax-report-ausn"
            element={
              <DirectorOrHead>
                <TaxReportAusn />
              </DirectorOrHead>
            }
          />
          <Route
            path="tax-report-usn"
            element={
              <DirectorOrHead>
                <TaxReportUsn />
              </DirectorOrHead>
            }
          />
          <Route
            path="tax-report-usn-vat5"
            element={
              <DirectorOrHead>
                <TaxReportUsnVat5 />
              </DirectorOrHead>
            }
          />
          <Route
            path="tax-report-usn-vat7"
            element={
              <DirectorOrHead>
                <TaxReportUsnVat7 />
              </DirectorOrHead>
            }
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
            path="capitalization"
            element={
              <DirectorOrHead>
                <Capitalization />
              </DirectorOrHead>
            }
          />
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
      </PeriodProvider>
    </AuthProvider>
  );
}
