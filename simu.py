import pinocchio as se3
from pinocchio.robot_wrapper import RobotWrapper
from pinocchio.utils import *
from math import pi,sqrt,cos,sin
from hrp2_reduced import Hrp2Reduced
import time 

def ForceVect(force_list):
    '''Convert a list of forces into a StdVect_Force'''
    res = se3.StdVect_Force()
    res.extend(f for f in force_list)
    return res

def ForceDict(force_dict,N):
    '''Convert a dict of forces into a StdVect_Force'''
    res = se3.StdVect_Force()
    res.extend(se3.Force.Zero() if i not in force_dict else force_dict[i] for i in range(N) )
    return res


class Simu:
    '''
    Based on a Hrp2Reduced robot model, implement the simulation with spring
    contact at the 2 ankles.
    '''

    def __init__(self,robot,q0=None,dt=1e-3,ndt=10):
        '''
        Initialize from a Hrp2Reduced robot model, an initial configuration,
        a timestep dt and a number of Eurler integration step ndt.
        The <simu> method (later defined) processes <ndt> steps, each of them lasting <dt>/<ndt> seconds,
        (i.e. total integration time when calling simu is <dt> seconds).
        <q0> should be an attribute of robot if it is not given.
        '''
        self.frf = zero(6)
        self.flf = zero(6)
        self.dt  = dt       # Time step
        self.ndt = ndt      # Discretization (number of calls of step per time step)
        self.robot = robot

        self.NQ = robot.model.nq
        self.NV = robot.model.nv
        self.NB = robot.model.nbodies
        self.RF = robot.model.getFrameId('rankle')
        self.LF = robot.model.getFrameId('lankle')
        self.RK = robot.model.frames[self.RF].parent
        self.LK = robot.model.frames[self.LF].parent
        NQ,NV,NB,RF,LF,RK,LK = self.NQ,self.NV,self.NB,self.RF,self.LF,self.RK,self.LK

        if q0 is None: q0 = robot.q0
        se3.forwardKinematics(robot.model,robot.data,q0)
        se3.framesKinematics(robot.model,robot.data)

        self.Mrf0 = robot.data.oMf[RF].copy()  # Initial (i.e. 0-load) position of the R spring.
        self.Mlf0 = robot.data.oMf[LF].copy()  # Initial (i.e. 0-load) position of the L spring.

        self.Krf = -np.diagflat([20000.,200000.,00.])   # Stiffness of the Right spring
        self.Klf = -np.diagflat([20000.,200000.,00.])   # Stiffness of the Left  spring

        robot.viewer.addXYZaxis('world/mrf',[1.,.6,.6,1.],.03,.1)
        robot.viewer.addXYZaxis('world/mlf',[.6,.6,1.,1.],.03,.1)
        robot.viewer.applyConfiguration('world/mrf',se3ToXYZQUAT(self.Mrf0))
        robot.viewer.applyConfiguration('world/mlf',se3ToXYZQUAT(self.Mlf0))

    def step(self,q,vq,tauq,dt = None):
        if dt is None: dt = self.dt

        robot = self.robot
        NQ,NV,NB,RF,LF,RK,LK = self.NQ,self.NV,self.NB,self.RF,self.LF,self.RK,self.LK

        # --- Simu
        se3.forwardKinematics(robot.model,robot.data,q,v)
        se3.framesKinematics(robot.model,robot.data)
        
        Mrf = self.Mrf0.inverse()*robot.data.oMf[RF]
        vrf = robot.model.frames[RF].placement.inverse()*robot.data.v[RK]
        Mlf = self.Mlf0.inverse()*robot.data.oMf[LF]
        vlf = robot.model.frames[LF].placement.inverse()*robot.data.v[LK]

        qrf = np.vstack([Mrf.translation[1:],se3.rpy.matrixToRpy(Mrf.rotation)[0]])
        qlf = np.vstack([Mlf.translation[1:],se3.rpy.matrixToRpy(Mlf.rotation)[0]])

        frf = self.frf                                                  # Buffer where to store right force
        frf[[1,2,3]] = self.Krf*qrf                                     # Right force in effector frame
        rf0_frf = se3.Force(frf)                                        # Force in rf0 frame
        rk_frf  = (robot.data.oMi[RK].inverse()*self.Mrf0).act(rf0_frf) # Spring force in R-knee frame.
        flf = self.flf                                                  # Buffer where to store left force
        flf[[1,2,3]] = self.Klf*qlf                                     # Left force in effector frame
        lf0_flf = se3.Force(flf)                                        # Force in lf0 frame
        lk_flf  = (robot.data.oMi[LK].inverse()*self.Mlf0).act(lf0_flf) # Spring force in L-knee frame.

        self.forces = ForceDict({ RK: rk_frf, LK: lk_flf},NB)           # Argument to ABA

        aq  = se3.aba(robot.model,robot.data,q,vq,tauq,self.forces)
        vq += aq*dt
        q   = se3.integrate(robot.model,q,vq*dt)

        self.aq = aq
        return q,vq

    def simu(self,q,v,tau):
        '''Simu performs self.ndt steps each lasting self.dt/self.ndt seconds.'''
        for i in range(self.ndt):
            q,v = self.step(q,v,tau,self.dt/self.ndt)
        return q,v

    __call__ = simu


if __name__ == "__main__":
    '''Simulation using a simple PD controller.'''


    pkg = '/home/nmansard/src/sot_versions/groovy/ros/stacks/hrp2/'
    urdf = '/home/nmansard/src/pinocchio/pinocchio/models/hrp2014.urdf'
    robot = Hrp2Reduced(urdf,[pkg],loadModel=True)
    robot.display(robot.q0)
    robot.viewer.setCameraTransform(0,[1.9154722690582275,
                                       -0.2266872227191925,
                                       0.1087859719991684,
                                       0.5243823528289795,
                                       0.518651008605957,
                                       0.4620114266872406,
                                       0.4925136864185333])

    class ControlPD:
        def __init__(self,K):
            self.setGains(K)
        def setGains(self,P,V=None):
            if V is None: V=2*sqrt(P)
            self.P,self.V = P,V
        def control(self,q,v):
            return np.vstack([zero(3),-self.P*(q-robot.q0)[4:] - self.V*v[3:]])
        __call__ = control

    simu = Simu(robot,dt=1e-3,ndt=5)
    control = ControlPD(10000)

    #robot.model.gravity.linear=zero(3)

    def loop(q,v,niter,ndt=None,dt=None,tsleep=.9,fdisplay=1):
        t0 = time.time()
        if dt  is not None: simu.dt  = dt
        if ndt is not None: simu.ndt = ndt
        robot.display(q)
        for i in range(niter):
            q,v = simu(q,v,control(q,v))
            if not i % fdisplay:
                robot.display(q)
                time.sleep(tsleep*simu.dt)
        print 'Elapsed time = %.2f (simu time=%.2f)' % (time.time()-t0,simu.dt*niter)
        return q,v

    q = robot.q0.copy()
    v = zero(simu.NV)

    q[0]-=.02
    q[1]-=.02

    q0 = q.copy()
    v0 = v.copy()
